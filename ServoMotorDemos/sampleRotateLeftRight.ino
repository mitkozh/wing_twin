#include <AccelStepper.h>

// Define the Arduino pins connected to the driver
const int stepPin = 2; // Connected to PUL+
const int dirPin = 3;  // Connected to DIR+

// Define the motor interface type. 
// "1" means a dedicated driver with Step and Direction pins
#define MOTOR_INTERFACE_TYPE 1

// Initialize the AccelStepper object
AccelStepper stepper(MOTOR_INTERFACE_TYPE, stepPin, dirPin);

void setup() {
  // Set the maximum speed the motor can accelerate up to (steps per second)
  stepper.setMaxSpeed(600);
  
  // Set the acceleration rate (steps per second squared)
  stepper.setAcceleration(200);
  
  // Set an initial target position (e.g., 1600 steps = 1 full rotation if microstepping is at 8)
  stepper.moveTo(1600);
}

void loop() {
  // If the motor reaches its target position, tell it to move back to the start
  if (stepper.distanceToGo() == 0) {

    delay(150); // Pause for 150 milliseconds to let the system settle down

    // If it's at position 1600, move back to 0. If it's at 0, move to 1600.
    if (stepper.currentPosition() == 1600) {
      stepper.moveTo(0);
    } else {
      stepper.moveTo(1600);
    }
  }

  // CRITICAL: This function must be called as frequently as possible inside loop().
  // It calculates the exact physics equations and steps the motor when necessary.
  stepper.run();
}