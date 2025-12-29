#!/usr/bin/env python
# -*- coding: utf-8 -*-
import json
import logging
import os

import signal
import sys
import time
import threading
from typing import Dict, Any


from datetime import datetime
 
import paho.mqtt.client as mqtt

__author__ = ["Marcel Verpaalen"]
__version__ = "1.2"
__copyright__ = "Copyright 2023-2026, Marcel Verpaalen"
__license__ = "GPL 3.0"

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S%z",
    level=logging.DEBUG if os.getenv("LOG_LEVEL") == "DEBUG" else logging.INFO,
)

# Configuration - Consider moving to config file or environment variables
VICTRON_BROKER = os.getenv("VICTRON_BROKER", "192.168.3.77")
SOURCE_MQTT_BROKER = os.getenv("SOURCE_MQTT_BROKER", "192.168.3.10")
MQTT_TOPIC = os.getenv("MQTT_TOPIC", "/energy/meter")
WILL_TOPIC = os.getenv("WILL_TOPIC", "/energy/status_dbus_mapper")
VICTRON_TOPIC = os.getenv("VICTRON_TOPIC", "/dbus-mqtt-services")
DEBUG_LOG_MAPPING = os.getenv("DEBUG_LOG_MAPPING", "False").lower() == "true"


class P1Mapper:
    """
    Maps P1 meter data to D-Bus format for Victron VenusOS.
    
    Subscribes to energy meter MQTT messages and publishes them in D-Bus format
    to be consumed by dbus-mqtt-services on VenusOS.
    This can be picked up by the dbus-mqtt-services.py (https://github.com/marcelrv/dbus-mqtt-services) script and published to the Victron D-Bus.

    """

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.logger.info("Starting Victron DBUS MQTT message mapper v%s", __version__)
        self.logger.info("Source MQTT broker: %s", SOURCE_MQTT_BROKER)
        self.logger.info("Victron MQTT broker: %s", VICTRON_BROKER)

        # Connection states
        self.source_connected = False
        self.victron_connected = False
        self.processing_lock = threading.Lock()
        
        # Message counter
        self.index = 0
        
        # Load configuration
        try:
            config_path = os.path.join(os.path.dirname(__file__), "mapper.json")
            with open(config_path, encoding="utf-8") as f:
                dataload = json.load(f)
            self.device = dataload["device"]
            self.mapping: list = dataload["dbus_fields"]
            self.logger.info("Loaded %d field mappings", len(self.mapping))
        except Exception as e:
            self.logger.error("Failed to load mapper.json: %s", e)
            raise

        # Setup MQTT clients
        self.setup_mqtt_victron()
        self.setup_mqtt_source()
        
        # Start MQTT loops
        self.mqtt_client_victron.loop_start()
        self.mqtt_client_source.loop_start()
        
        self.logger.info("Mapper initialized and running")

    def setup_mqtt_source(self):
        """Setup connection to source MQTT broker (energy meter)."""
        self.logger.info("Setting up source MQTT broker connection: %s", SOURCE_MQTT_BROKER)
        self.mqtt_client_source = mqtt.Client(client_id="p1_mapper_source")
        self.mqtt_client_source.on_connect = self.on_connect_source
        self.mqtt_client_source.on_message = self.on_message
        self.mqtt_client_source.on_disconnect = self.on_disconnect_source
        self.mqtt_client_source.will_set(WILL_TOPIC, "Dbus mapper offline", retain=True)
        
        try:
            self.mqtt_client_source.connect(SOURCE_MQTT_BROKER, 1883, 60)
        except Exception as e:
            self.logger.error("Failed to connect to source broker: %s", e)
            raise

    def setup_mqtt_victron(self):
        """Setup connection to Victron MQTT broker."""
        self.logger.info("Setting up Victron MQTT broker connection: %s", VICTRON_BROKER)
        self.mqtt_client_victron = mqtt.Client(client_id="p1_mapper_victron")
        self.mqtt_client_victron.on_connect = self.on_connect_victron
        self.mqtt_client_victron.on_disconnect = self.on_disconnect_victron
        
        # Set will message with disconnected status
        will_msg = {
            **self.device,
            "dbus_data": [
                {
                    "path": "/Connected",
                    "value": 0,
                    "valueType": "integer",
                    "writeable": False,
                }
            ]
        }
        self.mqtt_client_victron.will_set(
            VICTRON_TOPIC, 
            json.dumps(will_msg), 
            retain=True
        )
        
        try:
            self.mqtt_client_victron.connect_async(VICTRON_BROKER, 1883, keepalive=30)
        except Exception as e:
            self.logger.error("Failed to connect to Victron broker: %s", e)
            raise

    def on_connect_source(self, client, userdata, flags, rc):
        """Callback for source broker connection."""
        if rc == 0:
            self.logger.info("Source broker connected successfully")
            self.source_connected = True
            client.subscribe(MQTT_TOPIC)
            client.publish(
                WILL_TOPIC,
                f"Dbus mapper online {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                retain=True,
            )
        else:
            self.logger.error(
                "Source broker connection failed with code %d: %s",
                rc, RC_DESCRIPTIONS.get(rc, "Unknown")
            )
            self.source_connected = False

    def on_connect_victron(self, client, userdata, flags, rc):
        """Callback for Victron broker connection."""
        if rc == 0:
            self.logger.info("Victron broker connected successfully")
            self.victron_connected = True
        else:
            self.logger.error(
                "Victron broker connection failed with code %d: %s",
                rc, RC_DESCRIPTIONS.get(rc, "Unknown")
            )
            self.victron_connected = False

    def on_disconnect_source(self, client, userdata, rc):
        """Callback for source broker disconnection."""
        self.source_connected = False
        if rc != 0:
            self.logger.warning(
                "Unexpected source broker disconnection (code %d: %s)",
                rc, RC_DESCRIPTIONS.get(rc, "Unknown")
            )

    def on_disconnect_victron(self, client, userdata, rc):
        """Callback for Victron broker disconnection."""
        self.victron_connected = False
        if rc != 0:
            self.logger.warning(
                "Unexpected Victron broker disconnection (code %d: %s)",
                rc, RC_DESCRIPTIONS.get(rc, "Unknown")
            )

    def on_message(self, client, userdata, message):
        """Handle incoming messages from source broker."""
        self.logger.debug("Message received on topic: %s", message.topic)
        
        if message.topic != MQTT_TOPIC:
            return
            
        if not self.victron_connected:
            self.logger.warning("Message skipped: Victron broker not connected")
            return
        
        # Use lock to prevent concurrent processing
        if not self.processing_lock.acquire(blocking=False):
            self.logger.warning("Message skipped: Previous message still processing")
            return
        
        try:
            payload = message.payload.decode("utf-8")
            self.logger.debug("Message content: %s", payload)
            self.process_message(payload)
        except Exception as e:
            self.logger.error("Error processing message: %s", e, exc_info=True)
        finally:
            self.processing_lock.release()

    def process_message(self, payload: str):
        """
        Transform and publish message to Victron broker.
        
        Args:
            payload: JSON string from source broker
        """
        try:
            meter_data = json.loads(payload)
        except json.JSONDecodeError as e:
            self.logger.error("Invalid JSON in message: %s", e)
            return
        
        # Build D-Bus data array
        dbus_data = []
        
        for field in self.mapping:
            if "path" not in field or "name" not in field:
                continue
                
            field_name = field["name"]
            if field_name not in meter_data:
                continue
            
            if DEBUG_LOG_MAPPING:
                self.logger.debug("Mapping field: %s", field_name)
            
            value = meter_data[field_name]
            
            # Apply multiplier if specified
            if "multiplier" in field:
                value = value * field["multiplier"]
            
            # Build D-Bus record
            dbus_record = {
                "path": field["path"],
                "value": value,
                "valueType": field["valueType"],
                "writeable": False,
            }
            
            # Add optional fields
            if "unit" in field:
                dbus_record["unit"] = field["unit"]
            if "digits" in field:
                dbus_record["digits"] = field["digits"]
            
            dbus_data.append(dbus_record)
        
        # Add connection status
        dbus_data.append({
            "path": "/Connected",
            "value": 1 if self.source_connected else 0,
            "valueType": "integer",
            "writeable": False,
        })
        
        # Add update index
        dbus_data.append({
            "path": "/UpdateIndex",
            "value": self.index % 256,
            "valueType": "integer",
            "writeable": False,
        })
        
        # Build complete message
        response = {
            **self.device,
            "dbus_data": dbus_data
        }
        
        # Publish to Victron broker
        self.publish_to_victron(response)
        
        # Update status periodically
        if self.index % 256 == 0 or self.index == 0:
            self.logger.info("Published message #%d", self.index)
            self.mqtt_client_source.publish(
                WILL_TOPIC,
                f"Dbus mapper online {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}. "
                f"Published message #{self.index}",
                retain=True,
            )
        
        if self.index == 0:
            self.logger.info("First message: %s", json.dumps(response, indent=2))
        elif DEBUG_LOG_MAPPING:
            self.logger.debug("Published message: %s", json.dumps(response, indent=2))
        
        self.index += 1

    def publish_to_victron(self, message: Dict[str, Any]):
        """
        Publish message to Victron broker.
        
        Args:
            message: Dictionary to publish as JSON
        """
        try:
            message_str = json.dumps(message)
            result = self.mqtt_client_victron.publish(VICTRON_TOPIC, message_str)
            
            if result.rc != mqtt.MQTT_ERR_SUCCESS:
                self.logger.error(
                    "Failed to publish message #%d: %s",
                    self.index, RC_DESCRIPTIONS.get(result.rc, f"Error code {result.rc}")
                )
            else:
                self.logger.debug("Successfully published message #%d", self.index)
                
        except Exception as e:
            self.logger.error("Exception publishing message: %s", e, exc_info=True)

    def run_forever(self):
        """Keep the mapper running."""
        def signal_handler(sig, frame):
            self.logger.info("Shutdown signal received")
            self.shutdown()
            sys.exit(0)
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        self.logger.info("Mapper running. Press Ctrl+C to exit.")
        
        try:
            # Keep main thread alive (cross-platform)
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            self.logger.info("Keyboard interrupt received")
            self.shutdown()

    def shutdown(self):
        """Clean shutdown of MQTT connections."""
        self.logger.info("Shutting down...")
        
        try:
            # Publish offline status
            self.mqtt_client_source.publish(WILL_TOPIC, "Dbus mapper offline", retain=True)
        except:
            pass
        
        # Stop MQTT loops
        self.mqtt_client_victron.loop_stop()
        self.mqtt_client_source.loop_stop()
        
        # Disconnect
        self.mqtt_client_victron.disconnect()
        self.mqtt_client_source.disconnect()
        
        self.logger.info("Shutdown complete")
  

# MQTT return code descriptions
RC_DESCRIPTIONS = {
    0: "Success",
    0: "Normal disconnection",
    0: "Granted QoS 0",
    1: "Granted QoS 1",
    2: "Granted QoS 2",
    4: "Disconnect with Will Message",
    16: "No matching subscribers",
    17: "No subscription existed",
    24: "Continue authentication",
    25: "Re-authenticate",
    128: "Unspecified error",
    129: "Malformed Packet",
    130: "Protocol Error",
    131: "Implementation specific error",
    132: "Unsupported Protocol Version",
    133: "Client Identifier not valid",
    134: "Bad User Name or Password",
    135: "Not authorized",
    136: "Server unavailable",
    137: "Server busy",
    138: "Banned",
    139: "Server shutting down",
    140: "Bad authentication method",
    141: "Keep Alive timeout",
    142: "Session taken over",
    143: "Topic Filter invalid",
    144: "Topic Name invalid",
    145: "Packet Identifier in use",
    146: "Packet Identifier not found",
    147: "Receive Maximum exceeded",
    148: "Topic Alias invalid",
    149: "Packet too large",
    150: "Message rate too high",
    151: "Quota exceeded",
    152: "Administrative action",
    153: "Payload format invalid",
    154: "Retain not supported",
    155: "QoS not supported",
    156: "Use another server",
    157: "Server moved",
    158: "Shared Subscriptions not supported",
    159: "Connection rate exceeded",
    160: "Maximum connect time",
    161: "Subscription Identifiers not supported",
    162: "Wildcard Subscriptions not supported",
}


if __name__ == "__main__":
    try:
        mapper = P1Mapper()
        mapper.run_forever()
    except Exception as e:
        logging.error("Fatal error: %s", e, exc_info=True)
        exit(1)