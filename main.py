import network
import socket
import select
import time
import json
import dht

from machine import Pin, PWM, SoftI2C, time_pulse_us
from machine_i2c_lcd import I2cLcd

# ==============================
# WIFI SETTINGS
# ==============================

ssid = " "
password = " "

# ==============================
# PIN SETUP
# ==============================

# DHT11 data pin
dht_sensor = dht.DHT11(Pin(33))

# HC-SR04 pins
trig = Pin(27, Pin.OUT)
echo = Pin(26, Pin.IN)

# SG90 servo signal pin
servo = PWM(Pin(13))
servo.freq(50)

# I2C LCD 16x2
I2C_ADDR = 0x27
LCD_COLS = 16

i2c = SoftI2C(sda=Pin(21), scl=Pin(22), freq=400000)
lcd = I2cLcd(i2c, I2C_ADDR, 2, LCD_COLS)

# ==============================
# SHARED STATE
# ==============================

# Latest sensor readings. Refreshed every SENSOR_INTERVAL_MS by the main
# loop, never per request - the DHT11 fails if it is read more than about
# once a second, and the page polls /data every 2 seconds.
SENSOR_INTERVAL_MS = 2000

temperature = None
humidity = None
distance = None
last_sensor_ms = time.ticks_ms() - SENSOR_INTERVAL_MS

# Task 2: which sensor rows are on the LCD
show_distance = False
show_temperature = False

# Task 3: angle the servo is holding
servo_angle = 90

# Task 4: custom message on the LCD.
# The LCD has one owner at a time: either the sensor rows or the message.
# Sending a message turns both sensor toggles off; turning a toggle on
# clears the message.
MESSAGE_MAX = 100
SCROLL_INTERVAL_MS = 350
SCROLL_GAP = "    "

message = ""
lcd_showing_ip = False
scroll_pos = 0
last_scroll_ms = 0

# ==============================
# SENSORS
# ==============================

def read_distance():
    try:
        # set Trigger to off for 2us
        trig.value(0)
        time.sleep_us(2)

        # set Trigger to on for 10us
        trig.value(1)
        time.sleep_us(10)

        # set Trigger to off again
        trig.value(0)

        # Measure the ECHO pulse, give up after 30 ms
        duration = time_pulse_us(echo, 1, 30000)

        if duration < 0:
            return None

        # Convert time to distance in centimetres with d = v*t/2
        return (duration * 0.0343) / 2

    except Exception as error:
        print("Ultrasonic error:", error)
        return None


def read_dht11():
    try:
        dht_sensor.measure()
        return dht_sensor.temperature(), dht_sensor.humidity()

    except Exception as error:
        print("DHT11 error:", error)
        return None, None


def update_sensors():
    global temperature, humidity, distance

    temperature, humidity = read_dht11()
    distance = read_distance()

    if show_distance:
        display_distance()

    if show_temperature:
        display_temperature()

# ==============================
# LCD
# ==============================

def lcd_line(row, text):

    # Pad to the full width so a shorter value overwrites
    # every character of the longer one it replaces
    lcd.move_to(0, row)
    lcd.putstr((text + " " * LCD_COLS)[:LCD_COLS])


def display_distance():

    if distance is None:
        lcd_line(0, "Distance Error")
    else:
        lcd_line(0, "Dist: {:.1f} cm".format(distance))


def display_temperature():

    if temperature is None:
        lcd_line(1, "Temp Error")
    else:
        lcd_line(1, "Temp: {} C".format(temperature))


def show_message(text):
    global message, lcd_showing_ip, scroll_pos, last_scroll_ms
    global show_distance, show_temperature

    message = text
    lcd_showing_ip = False
    scroll_pos = 0
    last_scroll_ms = time.ticks_ms()

    show_distance = False
    show_temperature = False

    lcd.clear()
    lcd_line(0, message)


def clear_message():
    global message, lcd_showing_ip

    message = ""
    lcd_showing_ip = False
    lcd.clear()

    if show_distance:
        display_distance()

    if show_temperature:
        display_temperature()


def scroll_step():
    global scroll_pos, last_scroll_ms

    # Messages that fit on one row are static
    if len(message) <= LCD_COLS:
        return

    if time.ticks_diff(time.ticks_ms(), last_scroll_ms) < SCROLL_INTERVAL_MS:
        return

    # One step per call instead of a blocking loop, so the web server
    # keeps answering while a long message crosses the screen
    loop_text = message + SCROLL_GAP
    window = (loop_text + loop_text)[scroll_pos:scroll_pos + LCD_COLS]
    lcd_line(0, window)

    scroll_pos = (scroll_pos + 1) % len(loop_text)
    last_scroll_ms = time.ticks_ms()


def toggle(item):
    global show_distance, show_temperature

    # The sensor rows take the LCD back from a custom message
    # or from the startup IP screen
    if message or lcd_showing_ip:
        clear_message()

    if item == "distance":
        show_distance = not show_distance

        if show_distance:
            display_distance()
        else:
            lcd_line(0, "")

    elif item == "temperature":
        show_temperature = not show_temperature

        if show_temperature:
            display_temperature()
        else:
            lcd_line(1, "")

# ==============================
# SERVO
# ==============================

# A hobby servo reads the width of the HIGH pulse in a 20 ms frame:
#   ~500 us  -> 0 degrees
#   ~2500 us -> 180 degrees
PULSE_MIN_US = 500
PULSE_MAX_US = 2500
PERIOD_US = 20000

# Different MicroPython builds expose different duty methods
HAS_DUTY_NS = hasattr(servo, "duty_ns")
HAS_DUTY_U16 = hasattr(servo, "duty_u16")


def move_servo(angle):

    # Keep the angle between 0 and 180 degrees
    angle = max(0, min(180, angle))

    pulse_us = PULSE_MIN_US + (angle / 180) * (PULSE_MAX_US - PULSE_MIN_US)

    if HAS_DUTY_NS:
        servo.duty_ns(int(pulse_us * 1000))
    elif HAS_DUTY_U16:
        servo.duty_u16(int((pulse_us / PERIOD_US) * 65535))
    else:
        servo.duty(int((pulse_us / PERIOD_US) * 1023))

    print("Servo angle:", angle, "| pulse us:", int(pulse_us))

    return angle

# ==============================
# REQUEST HELPERS
# ==============================

def url_decode(text):

    result = bytearray()
    index = 0

    while index < len(text):

        if text[index] == "+":
            # Convert + to a space
            result.append(32)
            index += 1

        elif text[index] == "%":
            try:
                result.append(int(text[index + 1:index + 3], 16))
                index += 3
            except Exception:
                index += 1

        else:
            result.extend(text[index].encode())
            index += 1

    try:
        return result.decode("utf-8")
    except Exception:
        return str(result)


def lcd_safe(text):

    # The HD44780 only has printable ASCII in common with the browser,
    # anything else would show up as a garbage glyph
    return "".join(c if 32 <= ord(c) < 127 else "?" for c in text)


def get_param(path, name):

    if "?" not in path:
        return None

    for pair in path.split("?", 1)[1].split("&"):
        if pair.startswith(name + "="):
            return url_decode(pair[len(name) + 1:])

    return None


def state_json():

    return json.dumps({
        "temperature": temperature,
        "humidity": humidity,
        "distance": None if distance is None else round(distance, 1),
        "show_distance": show_distance,
        "show_temperature": show_temperature,
        "servo_angle": servo_angle,
        "message": message,
    })


def send_response(client, status, content_type=None, body=None):

    header = "HTTP/1.1 " + status + "\r\n"

    if content_type:
        header += "Content-Type: " + content_type + "\r\n"

    header += "Cache-Control: no-store\r\n"
    header += "Connection: close\r\n"
    header += "\r\n"

    client.sendall(header.encode())

    if body:
        client.sendall(body.encode())

# ==============================
# WEBPAGE
# ==============================

# The page is static. Live values arrive by fetch() from /data, so the
# textbox and slider are never wiped by a page reload.
WEBPAGE = """<!DOCTYPE html>
<html>
<head>
<title>ESP32 IoT Dashboard</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body {
    font-family: 'Segoe UI', Arial, sans-serif;
    text-align: center;
    background-color: #eeeeee;
    margin: 0;
    padding: 24px 16px;
}
h1 {
    color: #2c2c2c;
    font-size: 2rem;
    margin: 0 0 6px 0;
}
#connection {
    color: #777777;
    font-size: 0.9rem;
    margin: 0 0 20px 0;
}
#connection.offline {
    color: #f44336;
    font-weight: bold;
}
.card {
    background-color: #ffffff;
    max-width: 320px;
    margin: 0 auto 20px auto;
    padding: 22px 20px;
    border-radius: 18px;
    box-shadow: 0 4px 14px rgba(0, 0, 0, 0.12);
}
h2 {
    font-size: 1.3rem;
    color: #1a1a1a;
    margin: 0 0 16px 0;
}
.readings {
    display: flex;
    justify-content: space-around;
}
.label {
    color: #444444;
    font-size: 0.95rem;
    margin: 0 0 6px 0;
}
.value {
    color: #2f6fed;
    font-size: 1.6rem;
    font-weight: bold;
}
button {
    border: none;
    color: white;
    padding: 10px 18px;
    margin: 6px;
    border-radius: 8px;
    font-size: 15px;
    cursor: pointer;
}
.show-button {
    background-color: #4CAF50;
}
.hide-button {
    background-color: #f44336;
}
.send-button {
    background-color: #2f6fed;
}
.clear-button {
    background-color: #777777;
}
.angle {
    color: #cc3300;
    font-size: 2.4rem;
    font-weight: bold;
    margin: 0;
}
input[type="range"] {
    width: 100%;
    margin-top: 12px;
}
input[type="text"] {
    width: 100%;
    box-sizing: border-box;
    padding: 12px;
    font-size: 16px;
    border: 1px solid #cccccc;
    border-radius: 6px;
}
.note {
    color: #777777;
    font-size: 0.85rem;
    margin: 10px 0 0 0;
}
</style>
</head>
<body>

<h1>ESP32 IoT Dashboard</h1>
<p id="connection">Connecting...</p>

<div class="card">
    <h2>Sensors</h2>
    <div class="readings">
        <div>
            <p class="label">Temperature</p>
            <span class="value" id="temperature">--</span>
        </div>
        <div>
            <p class="label">Humidity</p>
            <span class="value" id="humidity">--</span>
        </div>
    </div>
    <p class="label" style="margin-top: 18px">Distance</p>
    <span class="value" id="distance">--</span>
</div>

<div class="card">
    <h2>LCD Sensor Display</h2>
    <button id="distance-button" class="show-button" onclick="toggleItem('distance')">Show Distance</button>
    <button id="temperature-button" class="show-button" onclick="toggleItem('temperature')">Show Temperature</button>
    <p class="note">Distance uses LCD line 1, temperature uses line 2.</p>
</div>

<div class="card">
    <h2>Servo Angle</h2>
    <p class="angle"><span id="angle-value">90</span>&deg;</p>
    <input type="range" id="slider" min="0" max="180" value="90"
        oninput="sliding = true; document.getElementById('angle-value').innerHTML = this.value"
        onchange="setAngle(this.value)">
</div>

<div class="card">
    <h2>LCD Message</h2>
    <input type="text" id="message" maxlength="100" placeholder="Enter your message">
    <br>
    <button class="send-button" onclick="sendMessage()">Send</button>
    <button class="clear-button" onclick="clearMessage()">Clear LCD</button>
    <p class="note" id="status">Messages over 16 characters scroll.</p>
</div>

<script>
var sliding = false;

function setText(id, text) {
    document.getElementById(id).innerHTML = text;
}

function setButton(id, shown, name) {
    var button = document.getElementById(id);
    button.innerHTML = (shown ? "Hide " : "Show ") + name;
    button.className = shown ? "hide-button" : "show-button";
}

function render(state) {
    setText("temperature", state.temperature === null ? "Error" : state.temperature + " &deg;C");
    setText("humidity", state.humidity === null ? "Error" : state.humidity + " %");
    setText("distance", state.distance === null ? "Out of range" : state.distance.toFixed(1) + " cm");

    setButton("distance-button", state.show_distance, "Distance");
    setButton("temperature-button", state.show_temperature, "Temperature");

    // Do not yank the slider out from under a drag in progress
    if (!sliding) {
        document.getElementById("slider").value = state.servo_angle;
        setText("angle-value", state.servo_angle);
    }

    var connection = document.getElementById("connection");
    connection.innerHTML = "Live - updates every 2 seconds";
    connection.className = "";
}

function request(url) {
    return fetch(url)
        .then(function (response) { return response.json(); })
        .then(render)
        .catch(function () {
            var connection = document.getElementById("connection");
            connection.innerHTML = "Lost connection to ESP32";
            connection.className = "offline";
        });
}

function toggleItem(item) {
    request("/toggle?item=" + item);
}

function setAngle(angle) {
    request("/servo?angle=" + angle).then(function () { sliding = false; });
}

function sendMessage() {
    var text = document.getElementById("message").value;

    if (text == "") {
        setText("status", "Please enter a message.");
        return;
    }

    request("/message?text=" + encodeURIComponent(text));
    setText("status", "Message sent to LCD.");
}

function clearMessage() {
    request("/clear");
    setText("status", "LCD cleared.");
}

document.getElementById("message").addEventListener("keydown", function (event) {
    if (event.key == "Enter") {
        sendMessage();
    }
});

request("/data");
setInterval(function () { request("/data"); }, 2000);
</script>

</body>
</html>
"""

# ==============================
# CONNECT TO WIFI
# ==============================

lcd.clear()
lcd_line(0, "IoT Group 3")
lcd_line(1, "Wi-Fi...")

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
        if password.strip():
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

    lcd_line(1, "Wi-Fi FAILED")
    raise SystemExit

ip = wifi.ifconfig()[0]

print()
print("Wi-Fi connected!")
print("ESP32 IP address:", ip)
print("Open this address in your browser:")
print("http://" + ip)

# Show the address on the LCD so the board can be used without a PC
lcd.clear()
lcd_line(0, "Open in browser:")
lcd_line(1, ip)
lcd_showing_ip = True

# ==============================
# START WEB SERVER
# ==============================

address = socket.getaddrinfo("0.0.0.0", 80)[0][-1]

server = socket.socket()
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind(address)
server.listen(2)

# poll() with a short timeout instead of a blocking accept(), so the loop
# keeps reading sensors and scrolling the LCD while nobody is connected
poller = select.poll()
poller.register(server, select.POLLIN)

print("Web server is running...")

servo_angle = move_servo(servo_angle)

# ==============================
# MAIN LOOP
# ==============================

while True:

    # ----------------------------------
    # BACKGROUND WORK
    # ----------------------------------

    if time.ticks_diff(time.ticks_ms(), last_sensor_ms) >= SENSOR_INTERVAL_MS:
        update_sensors()
        last_sensor_ms = time.ticks_ms()

    if message:
        scroll_step()

    if not poller.poll(50):
        continue

    # ----------------------------------
    # HANDLE ONE REQUEST
    # ----------------------------------

    client = None

    try:
        client, client_address = server.accept()
        client.settimeout(3.0)

        request = client.recv(1024).decode()

        if not request:
            continue

        request_line = request.split("\r\n")[0]
        parts = request_line.split(" ")

        if len(parts) < 2:
            send_response(client, "400 Bad Request")
            continue

        path = parts[1]
        route = path.split("?")[0]

        if route != "/data":
            print("Request:", request_line)

        # Task 1: live sensor values (polled by the page)
        if route == "/data":
            send_response(client, "200 OK", "application/json", state_json())

        # Task 2: sensor rows on the LCD
        elif route == "/toggle":
            toggle(get_param(path, "item"))
            send_response(client, "200 OK", "application/json", state_json())

        # Task 3: servo slider
        elif route == "/servo":
            try:
                servo_angle = move_servo(int(get_param(path, "angle")))
                send_response(client, "200 OK", "application/json", state_json())
            except Exception as error:
                print("Servo control error:", error)
                send_response(client, "400 Bad Request")

        # Task 4: custom message
        elif route == "/message":
            text = lcd_safe(get_param(path, "text") or "")[:MESSAGE_MAX]
            print("Message:", text)

            if text:
                show_message(text)
            else:
                clear_message()

            send_response(client, "200 OK", "application/json", state_json())

        elif route == "/clear":
            clear_message()
            send_response(client, "200 OK", "application/json", state_json())

        # Browsers ask for this unprompted
        elif route == "/favicon.ico":
            send_response(client, "404 Not Found")

        # Everything else gets the dashboard
        else:
            send_response(client, "200 OK", "text/html", WEBPAGE)

    except Exception as error:
        print("Server error:", error)

    finally:
        if client is not None:
            client.close()
