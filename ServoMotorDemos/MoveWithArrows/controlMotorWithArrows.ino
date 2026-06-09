#include <AccelStepper.h>

const int stepPin = 2; // Connected to PUL+
const int dirPin = 3;  // Connected to DIR+

#define MOTOR_INTERFACE_TYPE 1
AccelStepper stepper(MOTOR_INTERFACE_TYPE, stepPin, dirPin);

unsigned long lastCommandTime = 0;
const unsigned long timeoutMs = 200; // Stop motor if no key is pressed for 200ms

void setup() {
  Serial.begin(115200); // Set a fast baud rate for low-latency control
  
  // High max speed, but we will control the exact velocity manually
  stepper.setMaxSpeed(2000); 
  stepper.setAcceleration(1000);
}

void loop() {
  // Check if your computer sent a new keyboard command
  if (Serial.available() > 0) {
    char command = Serial.read();
    lastCommandTime = millis(); // Refresh the active timer

    if (command == 'F') {
      // Set constant forward speed (approx 22.5 RPM at 1600 steps/rev)
      stepper.setSpeed(600); 
    } 
    else if (command == 'B') {
      // Set constant backward speed
      stepper.setSpeed(-600); 
    }
  }

  // Safety Timeout: If you release the arrow key, stop the motor smoothly
  if (millis() - lastCommandTime > timeoutMs) {
    stepper.setSpeed(0);
  }

  // Constant speed mode requires calling runSpeed() instead of run()
  stepper.runSpeed();
}