import network
import socket
import time

from machine import Pin, SoftI2C
from machine_i2c_lcd import I2cLcd

# WIFI SETTINGS

ssid = " "
password = " "

# LCD SETUP

I2C_ADDR = 0x27  ## Add the LCD Address

i2c = SoftI2C(
    sda=Pin(21),
    scl=Pin(22),
    freq=400000
)

lcd = I2cLcd(
    i2c,
    I2C_ADDR,
    2,
    16
)

lcd.clear()



### DECODE TEXT FROM URL

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
                hex_value = text[
                    index + 1:index + 3
                ]

                result.append(
                    int(hex_value, 16)
                )

                index += 3

            except:
                index += 1

        else:

            result.extend(
                text[index].encode()
            )

            index += 1

    try:
        return result.decode("utf-8")

    except:
        return str(result)


def display_message(message):
    lcd.clear()

    ### write a code in here to diplay the message on the LCD with lcd.putstr() if the lenght of the message is less than 16.
    ### If the message is more than 16, use lcd.scroll_text() to display the message
    if len(message) <= 16:
        lcd.putstr(message)
    else:
        lcd.scroll_text(message)


# CREATE WEBPAGE

def create_webpage():

    html = """
<!DOCTYPE html>

<html>

<head>

    <title>ESP32 LCD Control</title>

    <meta name="viewport"
          content="width=device-width,
                   initial-scale=1">

    <style>

        body {
            font-family: Arial;
            text-align: center;
            background-color: #ffe6f0;
            padding: 20px;
        }

        h1 {
            color: #d6336c;
        }

        .subtitle {
            color: #a3336c;
            font-size: 16px;
            margin-bottom: 15px;
        }

        .card {
            background-color: white;
            width: 320px;
            margin: 20px auto;
            padding: 20px;
            border-radius: 10px;

            box-shadow:
                0 2px 8px
                rgba(214, 51, 108, 0.3);
        }

        input[type="text"] {
            width: 260px;
            padding: 12px;
            font-size: 16px;
            border: 1px solid #f3a6c4;
            border-radius: 6px;
            margin-bottom: 15px;
        }

        button {
            background-color: #e83e8c;
            border: none;
            color: white;
            padding: 12px 24px;
            border-radius: 6px;
            font-size: 16px;
            cursor: pointer;
        }

        button:hover {
            background-color: #c2255c;
        }

        #status {
            color: #d6336c;
            margin-top: 15px;
            font-weight: bold;
        }

    </style>

    <script>

        function sendMessage() {

            var message =
                document.getElementById(
                    "message"
                ).value;

            if (message == "") {

                document.getElementById(
                    "status"
                ).innerHTML =
                    "Please enter a message.";

                return;
            }

            fetch(
                "/message?text=" +
                encodeURIComponent(message)
            );

            document.getElementById(
                "status"
            ).innerHTML =
                "Message sent to LCD";
        }

    </script>

</head>

<body>

    <h1>ESP32 LCD Control</h1>

    <!-- Add class card with the input to insert the message -->
    <div class="card">
        <p class="subtitle">Send a message to the LCD</p>
        <input type="text" id="message" placeholder="Enter your message">

        <br>

        <button onclick="sendMessage()">
            Send
        </button>

        <p id="status"></p>

    </div>

</body>

</html>
"""

    return html


wifi = network.WLAN(
    network.STA_IF
)

wifi.active(True)

if not wifi.isconnected():

    print("Connecting to Wi-Fi...")

    wifi.connect(
        ssid,
        password
    )

    while not wifi.isconnected():

        print(".", end="")
        time.sleep(1)

ip = wifi.ifconfig()[0]

print()
print("Wi-Fi connected!")
print("ESP32 IP address:", ip)
print("Open this address:")
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

# MAIN PROGRAM
while True:

    client = None

    try:
        client, client_address = (
            server.accept()
        )

        request = client.recv(1024)
        request = request.decode()

        request_line = request.split(
            "\r\n"
        )[0]

        print("Request:", request_line)


        # RECEIVE CUSTOM TEXT


        if "GET /message?text=" in request_line:

            start = request_line.find("text=") + len("text=")

            end = request_line.find(" HTTP")

            encoded_message = request_line[start:end]

            message = url_decode(encoded_message)

            print("Message:", message)

            # Respond before scrolling
            client.send(
                "HTTP/1.1 204 No Content\r\n"
            )

            client.send(
                "Connection: close\r\n"
            )

            client.send("\r\n")

            client.close()
            client = None

            # Display or scroll the message
            display_message(message)


        # SEND WEBPAGE


        else:

            webpage = create_webpage()

            client.send(
                "HTTP/1.1 200 OK\r\n"
            )

            client.send(
                "Content-Type: text/html\r\n"
            )

            client.send(
                "Connection: close\r\n"
            )

            client.send("\r\n")

            client.sendall(webpage)

    except Exception as error:

        print(
            "Server error:",
            error
        )

    finally:

        if client is not None:
            client.close()