import network
import socket
import time
import dht

from machine import Pin, time_pulse_us

## WIFI Setup

ssid = " "
password = " "

# DHT11 data pin
dht_sensor = dht.DHT11(Pin(33))

# HC-SR04 pins
TRIG = Pin(27, Pin.OUT)
echo = Pin(26, Pin.IN)


def read_distance():
    try:
        # set Trigger to off for 2us
        TRIG.value(0)
        time.sleep_us(2)

        # set Trigger to on for 10us
        TRIG.value(1)
        time.sleep_us(10)

        # set Trigger to off again
        TRIG.value(0)

        # Measure the ECHO pulse
        duration = time_pulse_us(echo, 1, 30000)

        # make a codition if the duration less than 0 return None
        if duration < 0:
            return None

        # Convert time to distance in centimetres with the formular d = v*t/2
        distance = (duration * 0.0343) / 2

        return distance

    except Exception as error:
        print("Ultrasonic error:", error)
        return None


def read_dht11():
    try:
        # Call the object from the dht library
        dht_sensor.measure()

        temperature = dht_sensor.temperature()
        humidity = dht_sensor.humidity()

        return temperature, humidity

    except Exception as error:
        print("DHT11 error:", error)
        return None, None


def create_webpage(temperature, humidity, distance):

    if temperature is None:
        temperature_text = "Sensor error"
    else:
        temperature_text = str(temperature) + " &deg;C"

    if humidity is None:
        humidity_text = "Sensor error"
    else:
        humidity_text = str(humidity) + " %"

    if distance is None:
        distance_text = "Out of range"
    else:
        distance_text = "{:.1f} cm".format(distance)

    html = """
<!DOCTYPE html>
<html>

<head>
    <title>ESP32 Sensor Monitoring</title>

    <meta name="viewport"
          content="width=device-width, initial-scale=1">

    <meta http-equiv="refresh" content="2">

    <style>
        body {
            font-family: 'Segoe UI', Arial, sans-serif;
            text-align: center;
            background-color: #eeeeee;
            margin: 0;
            padding: 30px 20px;
            min-height: 100vh;
            box-sizing: border-box;
        }

        h1 {
            color: #2c2c2c;
            font-size: 2.2rem;
            font-weight: 800;
            margin-bottom: 30px;
        }

        .card {
            background-color: #ffffff;
            width: 280px;
            margin: 0 auto 24px auto;
            padding: 28px 20px;
            border-radius: 18px;
            box-shadow: 0 4px 14px rgba(0, 0, 0, 0.12);
        }

        .sensor-title {
            font-size: 1.4rem;
            font-weight: 700;
            color: #1a1a1a;
            margin: 0 0 20px 0;
        }

        .reading {
            margin: 0 0 20px 0;
        }

        .reading:last-child {
            margin-bottom: 0;
        }

        .sensor-label {
            color: #444444;
            font-size: 1rem;
            font-weight: 400;
            margin: 0 0 8px 0;
        }

        .value {
            color: #2f6fed;
            font-size: 1.8rem;
            font-weight: 700;
        }
    </style>
</head>

<body>

    <h1>ESP32 Sensor Monitoring</h1>

    <div class="card">
        <p class="sensor-title">DHT11 Sensor</p>

        <div class="reading">
            <p class="sensor-label">Temperature</p>
            <span class="value">%TEMPERATURE%</span>
        </div>
        <div class="reading">
            <p class="sensor-label">Humidity</p>
            <span class="value">%HUMIDITY%</span>
        </div>
    </div>

    <div class="card">
        <p class="sensor-title">HC-SR04 Sensor</p>

        <div class="reading">
            <p class="sensor-label">Distance</p>
            <span class="value">%DISTANCE%</span>
        </div>
    </div>

</body>

</html>
"""

    html = html.replace("%TEMPERATURE%", temperature_text)
    html = html.replace("%HUMIDITY%", humidity_text)
    html = html.replace("%DISTANCE%", distance_text)

    return html


wifi = network.WLAN(network.STA_IF)

wifi.active(True)

if not wifi.isconnected():
    print("Connecting to Wi-Fi...")
    wifi.connect(ssid, password)

    while not wifi.isconnected():
        print(".", end="")
        time.sleep(1)

ip = wifi.ifconfig()[0]

print()
print("Wi-Fi connected!")
print("ESP32 IP address:", ip)
print("Open this address in your browser:")
print("http://" + ip)


# ==============================
# START WEB SERVER
# ==============================

address = socket.getaddrinfo(
    "0.0.0.0",
    80
)[0][-1]

server = socket.socket()

server.setsockopt(
    socket.SOL_SOCKET,
    socket.SO_REUSEADDR,
    1
)

server.bind(address)
server.listen(1)

print("Web server is running...")

while True:

    client = None

    try:
        client, client_address = server.accept()

        print("Browser connected:", client_address)

        # Receive browser request
        request = client.recv(1024)
        print("Request received")

        # Read sensors
        temperature, humidity = read_dht11()
        distance = read_distance()

        print("Temperature:", temperature)
        print("Humidity:", humidity)
        print("Distance:", distance)

        # Create webpage
        webpage = create_webpage(temperature, humidity, distance)

        # Send HTTP response
        client.send("HTTP/1.1 200 OK\r\n")
        client.send("Content-Type: text/html\r\n")
        client.send("Connection: close\r\n")
        client.send("\r\n")
        client.sendall(webpage)

    except Exception as error:
        print("Server error:", error)

    finally:
        if client is not None:
            client.close()