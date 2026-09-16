import network
import socket
import time

from machine import Pin, PWM

# ==============================
# WIFI SETTINGS
# ==============================

ssid = " "
password = " "

# ==============================
# SERVO SETUP
# ==============================

SERVO_PIN = 13

servo = PWM(Pin(SERVO_PIN))
servo.freq(50)

servo_angle = 90

# A 50 Hz PWM cycle is 20000 microseconds long.
# A hobby servo reads the width of the HIGH pulse:
#   ~500 us  -> 0 degrees
#   ~2500 us -> 180 degrees
# Widen or narrow these if your servo doesn't reach the ends
# or buzzes when it gets there.
PULSE_MIN_US = 500
PULSE_MAX_US = 2500
PERIOD_US = 20000

# Different MicroPython builds expose different duty methods.
# Older builds have duty() (0-1023), newer have duty_u16() (0-65535),
# and some have duty_ns() directly. Detect once at startup.
HAS_DUTY_NS = hasattr(servo, "duty_ns")
HAS_DUTY_U16 = hasattr(servo, "duty_u16")


def move_servo(angle):

    # Keep the angle between 0 and 180 degrees
    if angle < 0:
        angle = 0

    if angle > 180:
        angle = 180

    # Convert angle to a pulse width in microseconds
    pulse_us = PULSE_MIN_US + (angle / 180) * (PULSE_MAX_US - PULSE_MIN_US)

    if HAS_DUTY_NS:
        servo.duty_ns(int(pulse_us * 1000))
        reported = int(pulse_us * 1000)

    elif HAS_DUTY_U16:
        duty = int((pulse_us / PERIOD_US) * 65535)
        servo.duty_u16(duty)
        reported = duty

    else:
        duty = int((pulse_us / PERIOD_US) * 1023)
        servo.duty(duty)
        reported = duty

    print("Servo angle:", angle, "| pulse us:", int(pulse_us), "| duty:", reported)

    return angle


# ==============================
# WEBPAGE
# ==============================

def create_webpage(angle):

    html = """<!DOCTYPE html>
<html>
<head>
<title>ESP32 Servo Control</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body {
    font-family: Arial, sans-serif;
    text-align: center;
    background-color: #f2f2f2;
    padding: 20px;
}
h1 {
    color: #0b5394;
}
.card {
    background-color: white;
    width: 320px;
    margin: 20px auto;
    padding: 20px;
    border-radius: 10px;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
}
.angle {
    color: #cc3300;
    font-size: 40px;
    font-weight: bold;
}
input[type="range"] {
    width: 280px;
    margin-top: 20px;
}
</style>
</head>
<body>

<h1>ESP32 Servo Control</h1>

<div class="card">

    <h2>Servo Angle</h2>

    <p id="angle-value" class="angle">SERVO_ANGLE</p>

    <input
        type="range"
        min="0"
        max="180"
        value="SERVO_ANGLE"
        oninput="document.getElementById('angle-value').innerHTML = this.value"
        onchange="fetch('/servo?angle=' + this.value)"
    >

    <p>Move the slider to control the servo.</p>

</div>

</body>
</html>
"""

    html = html.replace("SERVO_ANGLE", str(angle))

    return html


# ==============================
# CONNECT TO WIFI
# ==============================

wifi = network.WLAN(network.STA_IF)

# Clear any radio state left over from a previous run.
# Calling connect() while the chip is still mid-connection
# is what raises "Wifi Internal Error".
wifi.active(False)
time.sleep(1)
wifi.active(True)
time.sleep(1)

try:
    wifi.disconnect()
except Exception:
    pass

time.sleep(1)

print("Connecting to Wi-Fi...")

connected = False

for try_number in range(3):

    try:
        if password:
            wifi.connect(ssid, password)
        else:
            wifi.connect(ssid)

    except Exception as error:
        print("connect() raised:", error)
        time.sleep(2)
        continue

    attempts = 0
    while not wifi.isconnected() and attempts < 20:
        print(".", end="")
        time.sleep(1)
        attempts += 1

    if wifi.isconnected():
        connected = True
        break

    print()
    print("Attempt", try_number + 1, "timed out. Status:", wifi.status())
    time.sleep(2)

if not connected:
    print()
    print("Wi-Fi connection FAILED.")
    print("Networks the ESP32 can actually see:")

    try:
        for net in wifi.scan():
            print("  ", net[0].decode(), "| channel", net[2], "| rssi", net[3])
    except Exception as error:
        print("   scan failed:", error)

    raise SystemExit

ip = wifi.ifconfig()[0]

print()
print("Wi-Fi connected!")
print("ESP32 IP address:", ip)
print("Open this address:")
print("http://" + ip)


# ==============================
# START WEB SERVER
# ==============================

address = socket.getaddrinfo("0.0.0.0", 80)[0][-1]

server = socket.socket()
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind(address)
server.listen(1)

print("Web server is running...")


# ==============================
# INITIAL SERVO POSITION
# ==============================

servo_angle = move_servo(servo_angle)


while True:

    client = None

    try:
        client, client_address = server.accept()
        client.settimeout(5.0)

        request = client.recv(1024)
        request = request.decode()

        if not request:
            continue

        request_line = request.split("\r\n")[0]
        print("Request:", request_line)

        # ----------------------------------
        # RECEIVE SLIDER ANGLE
        # ----------------------------------

        if "GET /servo?angle=" in request_line:

            try:
                start = request_line.find("angle=") + 6
                end = request_line.find(" ", start)

                if end == -1:
                    end = len(request_line)

                angle_text = request_line[start:end]
                servo_angle = int(angle_text)
                servo_angle = move_servo(servo_angle)

                client.send("HTTP/1.1 204 No Content\r\n")
                client.send("Connection: close\r\n")
                client.send("\r\n")

            except Exception as error:
                print("Servo control error:", error)

                client.send("HTTP/1.1 400 Bad Request\r\n")
                client.send("Connection: close\r\n")
                client.send("\r\n")

        # ----------------------------------
        # IGNORE FAVICON REQUESTS
        # ----------------------------------

        elif "GET /favicon.ico" in request_line:

            client.send("HTTP/1.1 404 Not Found\r\n")
            client.send("Connection: close\r\n")
            client.send("\r\n")

        # ----------------------------------
        # SEND MAIN WEBPAGE
        # ----------------------------------

        else:

            webpage = create_webpage(servo_angle)

            client.send("HTTP/1.1 200 OK\r\n")
            client.send("Content-Type: text/html\r\n")
            client.send("Connection: close\r\n")
            client.send("\r\n")

            client.sendall(webpage.encode())

    except Exception as error:
        print("Server error:", error)

    finally:
        if client is not None:
            client.close()