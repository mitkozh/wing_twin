import serial
import time
import keyboard

# Configure the serial port. CHANGE 'COM3' to match your Arduino port!
SERIAL_PORT = 'COM4' 
BAUD_RATE = 115200

try:
    # Open the serial gateway to the Arduino
    arduino = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=0.1)
    time.sleep(2) # Give the Arduino 2 seconds to reboot and clear its buffer
    print(f"Successfully connected to Arduino on {SERIAL_PORT}!")
    print("Controls: Hold [UP ARROW] to go forward, [DOWN ARROW] to go backward. Press [ESC] to quit.")

    while True:
        # Check if Up Arrow is pressed
        if keyboard.is_pressed('up'):
            arduino.write(b'F') # Send Forward byte
            time.sleep(0.05)    # Small delay to avoid flooding the buffer
            
        # Check if Down Arrow is pressed
        elif keyboard.is_pressed('down'):
            arduino.write(b'B') # Send Backward byte
            time.sleep(0.05)
            
        # Emergency exit condition
        if keyboard.is_pressed('esc'):
            print("\nExiting controller program.")
            break

except serial.SerialException:
    print(f"Error: Could not open port {SERIAL_PORT}. Check your connection or IDE!")
except PermissionError:
    print("Error: Access denied. Make sure your Arduino IDE Serial Monitor is CLOSED!")