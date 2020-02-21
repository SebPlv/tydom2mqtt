from homeassistant.helpers.entity import Entity
from homeassistant.components.sensor import PLATFORM_SCHEMA
import homeassistant.helpers.config_validation as cv
from datetime import datetime, timedelta
import voluptuous as vol
import logging
import sys

#main import#
import asyncio
import time
from datetime import datetime
import os
import sys


from .mqtt_client import MQTT_Hassio
from .tydom_websocket import TydomWebSocketClient

import socket
#main import#






CONF_TYDOM_MAC = 'tydomMAC'
CONF_TYDOM_IP = 'tydomIP'
CONF_TYDOM_PASSWORD = 'tydomPassword'
CONF_MQTT_IP = 'mqttIP'
CONF_MQTT_PORT = 'mqttPort'

SCAN_INTERVAL = timedelta(seconds=3600)



# Validation of the user's configuration
PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Optional(CONF_TYDOM_MAC): cv.string,
    vol.Optional(CONF_TYDOM_IP): cv.string,
    vol.Optional(CONF_TYDOM_PASSWORD): cv.string,
    vol.Optional(CONF_MQTT_IP): cv.string,
    vol.Optional(CONF_MQTT_PORT): cv.port
})


def setup_platform(hass, config, add_devices, discovery_info=None):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    logging.basicConfig(stream=sys.stderr, level=logging.DEBUG)
    logger = logging.getLogger("TYDOM2MQTT")
    logger.info("[tydom2mqtt] start")
    """Setup the sensor platform."""
    tydomMAC = config.get(CONF_TYDOM_MAC)
    tydomIP = config.get(CONF_TYDOM_IP)
    tydomPassword = config.get(CONF_TYDOM_PASSWORD)
    mqttIP = config.get(CONF_MQTT_IP)
    mqttPort = config.get(CONF_MQTT_PORT)
    # Creating client object
    hassio = MQTT_Hassio(mqttIP, mqttPort, "", "", False)
    # hassio_connection = loop.run_until_complete(hassio.connect())
    # Giving MQTT connection to tydom class for updating
    tydom = TydomWebSocketClient(mac=tydomMAC, host=tydomIP, password=tydomPassword, mqtt_client=hassio)
    # Start connection and get client connection protocol
    loop.run_until_complete(tydom.mqtt_client.connect())
    loop.run_until_complete(tydom.connect())
    # Giving back tydom client to MQTT client
    hassio.tydom = tydom
    add_devices([Tydom2MQTT(tydom,loop,logger)])


class Tydom2MQTT(Entity):
    """Representation of a Sensor."""

    def __init__(self, tydom, loop,logger):
        """Initialize the sensor."""
        logger.info('Start websocket listener and heartbeat')
        self._state = None
        self.logger=logger;
        tasks = [                                                             
          tydom.receiveMessage(),                                             
          tydom.heartbeat()                                                    
        ]                                                                      
        loop.run_until_complete(asyncio.wait(tasks))

    @property
    def name(self):
        """Return the name of the sensor."""
        return 'Tydom2MQTT'

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state

    @property
    def unit_of_measurement(self):
        """Return the unit of measurement."""
        return ""

    @property
    def device_state_attributes(self):
        """Return the device state attributes of the last update."""

        attrs = {
        }
        return attrs

    def update(self):
        """Fetch new state data for the sensor.
        This is the only method that should fetch new data for Home Assistant.
        """
        self.logger.debug("[tydom2mqtt] nothing to do") 
