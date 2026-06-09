#include <Arduino.h>
#include "Stepper_control.h"

// =====================================================
// [TEST ONLY]
// Standalone stepper motor test for ESP32.
// Replace main.cpp to run this test.
//
// Test objectives:
//   1. stepper_init() — GPIO configuration
//   2. Forward / reverse position tracking
//   3. Acceleration ramp timing verification
//   4. stepper_is_moving() correctness
//   5. Manual jog mode via Serial
// =====================================================

const long TEST_POS_1 = 800;
const long TEST_POS_2 = 0;
const long TEST_POS_3 = -800;

int testPhase = 0;
bool testComplete = false;

unsigned long lastStepTimestamp = 0;
unsigned long stepInterval_us = 0;

// -----------------------------------------------------
void printHeader(const char* title) {
    Serial.println();
    Serial.println("============================================");
    Serial.print("== ");
    Serial.print(title);
    Serial.println();
    Serial.println("============================================");
}

// -----------------------------------------------------
// Block until stepper reaches target; print timing info
// -----------------------------------------------------
void waitForStepper() {
    while (stepper_is_moving()) {
        unsigned long now = micros();

        if (lastStepTimestamp != 0) {
            stepInterval_us = now - lastStepTimestamp;
        }
        lastStepTimestamp = now;

        static unsigned long lastPrint = 0;
        if (millis() - lastPrint >= 50) {
            lastPrint = millis();

            Serial.print("  Pos: ");
            Serial.print(stepper_get_current_position());
            Serial.print("  | Interval: ");
            Serial.print(stepInterval_us);
            Serial.print(" us");
            Serial.print(stepInterval_us > 1500 ? " (ACCEL)" : " (CRUISE)");

            if (stepInterval_us > 0) {
                Serial.print("  | ~");
                Serial.print(1000000.0f / stepInterval_us, 1);
                Serial.print(" steps/s");
            }
            Serial.println();
        }

        stepper_loop();
    }

    Serial.print("  => At position: ");
    Serial.println(stepper_get_current_position());
    Serial.println("  => Motor stopped.");
    Serial.println();
}

// -----------------------------------------------------
// setup()
// -----------------------------------------------------
void setup() {
    Serial.begin(115200);
    delay(1000);

    Serial.println();
    Serial.println("============================================");
    Serial.println("  ESP32 Stepper Motor Test");
    Serial.println("============================================");
    Serial.println();

    printHeader("1. Initialization Test");
    stepper_init();

    Serial.print("  Initial position : ");
    Serial.println(stepper_get_current_position());
    Serial.print("  Initial is_moving: ");
    Serial.println(stepper_is_moving() ? "true" : "false");
    Serial.println("  => OK");
}

// -----------------------------------------------------
// loop()
// -----------------------------------------------------
void loop() {
    if (!testComplete) {
        switch (testPhase) {

            case 0:
                printHeader("2. Forward Move (0 -> 800)");
                stepper_set_target(TEST_POS_1);
                testPhase++;
                break;

            case 1:
                waitForStepper();
                Serial.print(stepper_get_current_position() == TEST_POS_1 ? "  => PASS" : "  => FAIL");
                Serial.println(" (forward 800)");
                testPhase++;
                break;

            case 2:
                printHeader("3. Reverse Move (800 -> 0)");
                stepper_set_target(TEST_POS_2);
                testPhase++;
                break;

            case 3:
                waitForStepper();
                Serial.print(stepper_get_current_position() == TEST_POS_2 ? "  => PASS" : "  => FAIL");
                Serial.println(" (reverse to 0)");
                testPhase++;
                break;

            case 4:
                printHeader("4. Negative Direction (0 -> -800)");
                stepper_set_target(TEST_POS_3);
                testPhase++;
                break;

            case 5:
                waitForStepper();
                Serial.print(stepper_get_current_position() == TEST_POS_3 ? "  => PASS" : "  => FAIL");
                Serial.println(" (negative -800)");
                testPhase++;
                break;

            case 6:
                printHeader("5. Return to Zero (-800 -> 0)");
                stepper_set_target(0);
                testPhase++;
                break;

            case 7:
                waitForStepper();
                Serial.print(stepper_get_current_position() == 0 ? "  => PASS" : "  => FAIL");
                Serial.println(" (return to 0)");
                testPhase++;
                break;

            case 8:
                printHeader("6. Acceleration Ramp Check");
                Serial.println("  Review timing above:");
                Serial.println("  - First ~200 steps: interval decr. (ACCEL label)");
                Serial.println("  - Middle steps:     interval ~1000 us (CRUISE)");
                Serial.println("  - Last ~200 steps:  interval incr. (ACCEL label)");
                testPhase++;
                break;

            case 9: {
                printHeader("7. Short Multi-Move");
                long moves[] = {100, 250, 50, 300, 0};
                bool allOk = true;

                for (int i = 0; i < 5; i++) {
                    stepper_set_target(moves[i]);
                    while (stepper_is_moving()) { stepper_loop(); }
                    long pos = stepper_get_current_position();
                    Serial.print("  Target ");
                    Serial.print(moves[i]);
                    Serial.print(" -> ");
                    Serial.print(pos);
                    if (pos == moves[i]) {
                        Serial.println(" OK");
                    } else {
                        Serial.println(" FAIL");
                        allOk = false;
                    }
                }
                Serial.print("  => ");
                Serial.println(allOk ? "ALL PASSED" : "SOME FAILED");
                testPhase++;
                break;
            }

            case 10:
                printHeader("=== AUTO TEST DONE ===");
                Serial.println();
                Serial.println("Manual Jog Mode:");
                Serial.println("  F  jog forward 200 steps");
                Serial.println("  B  jog backward 200 steps");
                Serial.println("  S  stop at current position");
                Serial.println("  P  print position / status");
                Serial.println("  R  rerun auto test");
                Serial.println();
                testComplete = true;
                break;
        }
        return;
    }

    // -- Interactive jog mode ---------------------------------
    if (Serial.available() > 0) {
        char c = Serial.read();
        switch (c) {
            case 'F': case 'f':
                stepper_set_target(stepper_get_current_position() + 200);
                Serial.println("[JOG] +200 steps");
                break;
            case 'B': case 'b':
                stepper_set_target(stepper_get_current_position() - 200);
                Serial.println("[JOG] -200 steps");
                break;
            case 'S': case 's':
                stepper_set_target(stepper_get_current_position());
                Serial.println("[JOG] stop");
                break;
            case 'P': case 'p':
                Serial.print("[STATUS] Position: ");
                Serial.print(stepper_get_current_position());
                Serial.print(" | Moving: ");
                Serial.println(stepper_is_moving() ? "yes" : "no");
                break;
            case 'R': case 'r':
                Serial.println("[TEST] Restart...");
                testPhase = 0;
                testComplete = false;
                break;
        }
    }

    stepper_loop();
}
