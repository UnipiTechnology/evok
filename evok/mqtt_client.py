import asyncio
import json
import logging
from typing import Callable, Union, List, Tuple

from tornado.ioloop import IOLoop

from .log import logger

import aiomqtt as mqtt


class ConfigurationStructure:
    """
    Definuje konfiguraci pro Communicator
    """
    def __init__(self, hostname: str, port: int = 1883, username: str = "", password: str = "", keepalive: int = 60,
                 qos: int = 0):
        self.hostname = hostname  # adresa brokera
        self.port = port
        self.username = username
        self.password = password
        self.keepalive = keepalive
        self.qos = qos

    def __str__(self):
        return f"ConfigurationStructure(hostname={self.hostname}, port={self.port})"


class MqttClient:
    """
    Komunikator ma na starosti komunikaci pomoci mqtt. Lze do neho
    registrovat vzdy na danny topic (endpoint) svoji callback funcki,
    kterou po prijeti zpravy na tento endpoint zavola.
    Umi posilat zpravy na prislusny topic (endpoint)
    """
    reconnect_interval = 5

    def __init__(self, conf: ConfigurationStructure, callback: Callable, topic: str = '', client_id: str = ''):
        """
        :param conf: configuracni struktura pro nastaveni komunikatoru
        """
        self.callback = callback
        self.topic = topic
        self.is_connected = False
        self.__client = mqtt.Client(hostname=conf.hostname,
                                    port=conf.port,
                                    keepalive=conf.keepalive,
                                    identifier=client_id)
        self.conf = conf
        self.for_send = []


    async def __on_message(self, msg: mqtt.Message):  # noqa
        """
        Pokud prijde zprava zpracuje a zavola prislusny callback
        :param msg: prijata zprava
        :return:
        """
        payload = msg.payload.decode()
        if self.callback is not None:
            data = None
            try:
                data = json.loads(payload)
                await self.callback(str(msg.topic), data)
            except Exception as E:
                if data is None:
                    logger.error(f"Error while parsing payload like JSON: {E}")
                else:
                    logger.error(f"Error in callback: {type(E).__name__}{E}")
            # print(f"received: {msg.topic}\t\t{len(self.published)}")
        else:
            logger.error(f"callback not found: {msg.topic}!")

    async def send_to(self, topic: str, data: dict):
        """
        posle zpravu na endpoint
        :param topic: mqtt topic na ktery se posle zpravy
        :param data: zprava, ktera se posle
        :return: None
        """
        msg = json.dumps(data)
        if self.is_connected:
            await self.__client.publish(topic, msg, retain=False)
        else:
            self.for_send.append({'topic': topic, 'data': data})

    def start(self, loop: IOLoop):
        loop.add_callback(lambda: self.run())

    async def run(self):
        """
        Nastavi a zahaji komunikaci (spusti poslouchaci smycku)
        """
        logging.debug(f"Initializing MQTT... hostname:'{self.conf.hostname}'   port:{self.conf.port}")

        while True:
            try:
                async with self.__client as client:
                    self.is_connected = True
                    pending, self.for_send = self.for_send, []
                    for item in pending:
                        await self.send_to(item['topic'], item['data'])
                    await client.subscribe(self.topic)
                    async for message in client.messages:
                        await self.__on_message(message)
            except mqtt.MqttError as error:
                self.is_connected = False
                print(f'Error "{error}". Reconnecting in {self.reconnect_interval} seconds.')
                await asyncio.sleep(self.reconnect_interval)

