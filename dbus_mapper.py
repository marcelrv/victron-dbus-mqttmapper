#!/usr/bin/env python
# -*- coding: utf-8 -*-
import copy
import json
import logging
import os
from datetime import datetime

import paho.mqtt.client as mqtt

__author__ = ["Marcel Verpaalen"]
__version__ = "1.1"
__copyright__ = "Copyright 2023, Marcel Verpaalen"
__license__ = "GPL"

#  v1.1  add will message to mqtt broker
# from dotenv import load_dotenv


# load_dotenv()
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S%z",
    level=logging.DEBUG if os.getenv("LOG_LEVEL") == "DEBUG" else logging.INFO,
)

VICTRON_BROKER = "192.168.3.77"
SOURCE_MQTT_BROKER = "192.168.3.17"
MQTT_TOPIC = "/energy/meter"
LOG_LEVEL = "INFO"
WILL_TOPIC = "/energy/status_dbus_mapper"
VICTRON_TOPIC = "W/dbus-mqtt-services"


class P1Mapper:
    """
    Class representing a P1 Mapper.

    This class is responsible for mapping P1 meter data (or other devices) to D-Bus format and publishing it to the MQTT broker running on the Victron VenusOS device.
    This can be picked up by the dbus-mqtt-services.py (https://github.com/marcelrv/dbus-mqtt-services) script and published to the Victron D-Bus.

    """

    connected = 0

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.logger.info("Starting Victron DBUS MQTT message mapper")
        self.logger.info(f"Source MQTT broker {VICTRON_BROKER}")
        self.logger.info(f"Vicron MQTT broker {SOURCE_MQTT_BROKER}")

        dataload = json.load(open(os.path.join(os.path.dirname(__file__), "mapper.json"), encoding="utf-8"))
        self.device = dataload["device"]
        self.mapping: list = dataload["dbus_fields"]
        self.setup_mqtt_victron()
        self.setup_mqtt_p1()
        self.index = 0
        self.mqtt_client_victron.loop_start()
        self.mqtt_client_p1.loop_forever()

    def setup_mqtt_p1(self):
        self.logger.info(f"Setting up MQTT broker connection to {SOURCE_MQTT_BROKER}")
        self.mqtt_client_p1 = mqtt.Client(userdata=None)
        self.mqtt_client_p1.on_connect = self.on_connect
        self.mqtt_client_p1.on_message = self.on_message
        self.mqtt_client_p1.on_disconnect = self.on_disconnect
        self.mqtt_client_p1.will_set(WILL_TOPIC, "Dbus mapper offline", retain=True)
        self.mqtt_client_p1.connect(SOURCE_MQTT_BROKER, 1883, 60)

    def setup_mqtt_victron(self):
        self.logger.info(f"Setting up MQTT broker connection to {VICTRON_BROKER}")
        self.mqtt_client_victron = mqtt.Client(userdata=None)
        self.mqtt_client_victron.on_connect = self.on_connect_victron
        self.mqtt_client_victron.on_disconnect = self.on_disconnect_victron
        will = copy.deepcopy(self.device)
        will["dbus_data"] = [
            {
                "path": "/Connected",
                "value": 0,
                "valueType": "integer",
                "writeable": False,
            }
        ]
        self.mqtt_client_victron.will_set(VICTRON_TOPIC, json.dumps(will), retain=True)
        self.mqtt_client_victron.connect_async(
            VICTRON_BROKER,
            1883,
            keepalive=30,
        )

    def on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self.logger.info("Source broker Connection Established")
            self.connected = 1
        else:
            self.logger.warning(f"Source MQTT broker bad connection Returned code={rc}")
            self.connected = 0
        client.subscribe(MQTT_TOPIC)
        client.publish(
            WILL_TOPIC,
            f"Dbus mapper online {str(datetime.now().strftime('%d/%m/%Y %H:%M:%S'))}",
            retain=True,
        )

    def on_connect_victron(self, client, userdata, flags, rc):
        if rc == 0:
            self.logger.info("Victron MQTT broker Connection Established")
        else:
            self.logger.warning(f"Victron MQTT broker bad connection Returned code={rc}")

    def on_disconnect(self, client, userdata, rc):
        if rc != 0:
            self.logger.warning("Unexpected source MQTT disconnection. Will auto-reconnect")
            self.connected = 0

    def on_disconnect_victron(self, client, userdata, rc):
        if rc != 0:
            self.logger.warning("Unexpected Victron MQTT disconnection. Will auto-reconnect")

    def on_message(self, client, userdata, message):
        self.logger.debug(f"Message topic: {message.topic}")
        self.logger.debug(f"Message content: {message.payload.decode('utf-8')}")
        if message.topic == MQTT_TOPIC:
            self.logger.debug("Message received")
            self.mapper(message.payload.decode("utf-8"))

    def mapper(self, message):
        dbus_data = []
        meter = json.loads(message)
        response = copy.deepcopy(self.device)
        for field in self.mapping:
            if "path" in field and field["name"] in meter:
                key = field["name"]
                self.logger.debug(f"Field {field['name']} found in message {key}")
                value = meter[key]
                if "multiplier" in field:
                    value = value * field["multiplier"]
                dbus_record = {
                    "path": field["path"],
                    "value": value,
                    "valueType": field["valueType"],
                    "writeable": False,
                }
                if "unit" in field:
                    dbus_record["unit"] = field["unit"]
                if "digits" in field:
                    dbus_record["digits"] = field["digits"]
                dbus_data.append(dbus_record)

        # Add connected depending on the source mqqt connection and update index to ensure that the dbus service is updated
        dbus_data.append(
            {
                "path": "/Connected",
                "value": self.connected,
                "valueType": "integer",
                "writeable": False,
            }
        )
        dbus_data.append(
            {
                "path": "/UpdateIndex",
                "value": self.index % 256,
                "valueType": "integer",
                "writeable": False,
            }
        )
        response["dbus_data"].extend(dbus_data)
        response_str = json.dumps(response, indent=4)
        if self.index % 256 == 0:
            self.logger.info(f"Published message # {self.index}")
            self.mqtt_client_p1.publish(
                WILL_TOPIC,
                f"Dbus mapper online {str(datetime.now().strftime('%d/%m/%Y %H:%M:%S'))}. Published message # {self.index}",
                retain=True,
            )
        if self.index == 0:  # Always print the first message
            self.logger.info(f"Published message: {response_str}")
            self.mqtt_client_p1.publish(
                WILL_TOPIC,
                f"Dbus mapper online {str(datetime.now().strftime('%d/%m/%Y %H:%M:%S'))}. Published message # {self.index}",
                retain=True,
            )
        else:
            self.logger.debug(f"Published message: {response_str}")
        rc = self.mqtt_client_victron.publish(VICTRON_TOPIC, response_str)
        if rc[0] != 0:
            self.logger.warning(f"Error message # {self.index} during publish: {rc}")
        self.index += 1


if __name__ == "__main__":
    P1_mapper = P1Mapper()
