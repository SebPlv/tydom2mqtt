import asyncio
import websockets
import http.client
from requests.auth import HTTPDigestAuth
import sys
import logging
from http.client import HTTPResponse
from io import BytesIO
import urllib3
import json
import os
import base64
import time
from http.server import BaseHTTPRequestHandler
import ssl
from datetime import datetime
import subprocess, platform


from .cover import Cover
from .alarm_control_panel import Alarm


# Thanks https://stackoverflow.com/questions/49878953/issues-listening-incoming-messages-in-websocket-client-on-python-3-6


# Logging
logging.basicConfig(stream=sys.stderr, level=logging.DEBUG)
# http.client.HTTPSConnection.debuglevel = 1
# http.client.HTTPConnection.debuglevel = 1

# Dicts
deviceAlarmKeywords = ['alarmMode','alarmState','alarmSOS','zone1State','zone2State','zone3State','zone4State','zone5State','zone6State','zone7State','zone8State','gsmLevel','inactiveProduct','zone1State','liveCheckRunning','networkDefect','unitAutoProtect','unitBatteryDefect','unackedEvent','alarmTechnical','systAutoProtect','sysBatteryDefect','zsystSupervisionDefect','systOpenIssue','systTechnicalDefect','videoLinkDefect']
# Device dict for parsing
device_dict = dict()
climateKeywords = ['temperature', 'authorization', 'hvacMode', 'setpoint']


class TydomWebSocketClient():

    def __init__(self, mac, password, host='mediation.tydom.com', mqtt_client=None):
        self.logger = logging.getLogger("TYDOM2MQTTAPI")
        self.logger.debug('""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""')
        self.logger.debug('Initialising TydomClient Class')

        self.password = password
        self.mac = mac
        self.host = host
        self.mqtt_client = mqtt_client
        self.connection = None
        self.remote_mode = True
        self.ssl_context = None
        self.cmd_prefix = "\x02"

    async def connect(self):
        self.logger.debug('""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""')
        self.logger.debug('""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""')
        self.logger.debug('""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""')
        self.logger.debug('""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""')
        self.logger.debug('""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""')
        self.logger.debug('""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""')
        self.logger.debug('TYDOM WEBSOCKET CONNECTION INITIALISING....                     ')


        if not (self.host == 'mediation.tydom.com'):
            test = None
            testlocal = None
            try:
                self.logger.debug('Testing if local Tydom hub IP is reachable....')
                testlocal = subprocess.check_output("ping -{} 1 {}".format('n' if platform.system().lower()=="windows" else 'c', self.host), shell=True)
            except Exception as e:
                self.logger.error('Local control is down, will try to fallback to remote....')

            try:
                # raise Exception ## Uncomment to pure lcoal IP mode
                self.logger.debug('Testing if mediation.tydom.com is reacheable...')
                test = subprocess.check_output("ping -{} 1 {}".format('n' if platform.system().lower()=="windows" else 'c', 'mediation.tydom.com'), shell=True)
                self.logger.debug('mediation.tydom.com is reacheable ! Using it to prevent code 1006 deconnections from local ip for now.')
                self.host = 'mediation.tydom.com'
            except Exception as e:

                self.logger.error('Remote control is down !')

                if (testlocal == None) :
                    self.logger.error("Exiting to ensure systemd restart....")
                    sys.exit()
                else:
                    self.logger.error('Fallback to local ip for that connection, except code 1006 deconnections every 60 seconds...')

           
        # Set Host, ssl context and prefix for remote or local connection
        if self.host == "mediation.tydom.com":
            self.logger.debug('Setting remote mode context.')
            self.remote_mode = True
            self.ssl_context = None
            self.cmd_prefix = "\x02"
        else:
            self.logger.debug('Setting local mode context.')
            self.remote_mode = False
            self.ssl_context = ssl._create_unverified_context()
            self.cmd_prefix = ""

        self.logger.debug('Building headers, getting 1st handshake and authentication....')
        '''
            Connecting to webSocket server
            websockets.client.connect returns a WebSocketClientProtocol, which is used to send and receive messages
        '''
        httpHeaders =  {"Connection": "Upgrade",
                        "Upgrade": "websocket",
                        "Host": self.host + ":443",
                        "Accept": "*/*",
                        "Sec-WebSocket-Key": self.generate_random_key(),
                        "Sec-WebSocket-Version": "13"
                        }
        conn = http.client.HTTPSConnection(self.host, 443, context=self.ssl_context)
        # Get first handshake
        conn.request("GET", "/mediation/client?mac={}&appli=1".format(self.mac), None, httpHeaders)
        res = conn.getresponse()
        # Get authentication
        nonce = res.headers["WWW-Authenticate"].split(',', 3)
        # read response
        res.read()
        # Close HTTPS Connection
        conn.close()
        self.logger.debug('Upgrading http connection to websocket....')
        # Build websocket headers
        websocketHeaders = {'Authorization': self.build_digest_headers(nonce)}
        if self.ssl_context is not None:
            websocket_ssl_context = self.ssl_context
        else:
            websocket_ssl_context = True # Verify certificate


        try:
            self.logger.debug('Attempting websocket connection with tydom hub.......................')
            self.logger.debug('Host Target :')
            self.logger.debug(self.host)
            
            self.connection = await websockets.client.connect('wss://{}:443/mediation/client?mac={}&appli=1'.format(self.host, self.mac),
                                                    extra_headers=websocketHeaders, ssl=websocket_ssl_context)

            # async with websockets.client.connect('wss://{}:443/mediation/client?mac={}&appli=1'.format(self.host, self.mac),
            #                             extra_headers=websocketHeaders, ssl=websocket_ssl_context) as self.connection:
            await self.notify_alive()

            while True:
                self.logger.debug('\o/ \o/ \o/ \o/ \o/ \o/ \o/ \o/ \o/ ')
                self.logger.debug("Tydom Websocket is Connected !", self.connection)
                return self.connection

        except Exception as e:
            self.logger.error('Websocket def connect error')
            self.logger.error(e)
            self.logger.error('Exiting to ensure systemd restart....')
            sys.exit() #Exit all to ensure systemd restart
            # self.logger.debug('Reconnecting...')
            # asyncio.sleep(8)
            # await self.connect()

    async def heartbeat(self):
        '''
        Sending heartbeat to server
        Ping - pong messages to verify connection is alive
        '''
        self.logger.debug('Requesting 1st data...')

        await self.get_info()
        self.logger.debug("##################################")
        self.logger.debug("##################################")
        await self.post_refresh()
        await self.get_data()
        while self.connection.open:
            try:
                # await self.connection.send('ping')
                # await get_ping(self)
                # self.logger.debug('****** ping !')
                await self.post_refresh()
                await asyncio.sleep(40)


            except Exception as e:
                self.logger.error("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")

                self.logger.error('Heartbeat error')
                self.logger.error('Connection with server closed')
                self.logger.error(e)
                self.logger.error('Exiting to ensure systemd restart....')
                sys.exit() #Exit all to ensure systemd restart
                # self.logger.debug('Reconnecting...')
                # await self.connect()

# Send Generic GET message
    async def send_message(self, websocket, msg):
        if not self.connection.open:
            self.logger.error('Exiting to ensure systemd restart....')
            sys.exit() #Exit all to ensure systemd restart
            # self.logger.debug('Websocket not opened, reconnect...')
            # await self.connect()
   
        str = self.cmd_prefix + "GET " + msg +" HTTP/1.1\r\nContent-Length: 0\r\nContent-Type: application/json; charset=UTF-8\r\nTransac-Id: 0\r\n\r\n"
        a_bytes = bytes(str, "ascii")
        await websocket.send(a_bytes)
        self.logger.debug('GET Command send to websocket')
        return 0

# Send Generic POST message
    async def send_post_message(self, websocket, msg):
        if not self.connection.open:
            self.logger.error('Exiting to ensure systemd restart....')
            sys.exit() #Exit all to ensure systemd restart
            # self.logger.debug('Websocket not opened, reconnect...')
            # await self.connect()

        str = self.cmd_prefix + "POST " + msg +" HTTP/1.1\r\nContent-Length: 0\r\nContent-Type: application/json; charset=UTF-8\r\nTransac-Id: 0\r\n\r\n"
        a_bytes = bytes(str, "ascii")
        await websocket.send(a_bytes)
        # self.logger.debug('POST Command send to websocket')
        return 0

    # Give order (name + value) to endpoint
    async def put_devices_data(self, endpoint_id, name, value):
        if not self.connection.open:
            self.logger.error('Exiting to ensure systemd restart....')
            sys.exit() #Exit all to ensure systemd restart
            # self.logger.debug('Websocket not opened, reconnect...')
            # await self.connect()

        # For shutter, value is the percentage of closing
        body="[{\"name\":\"" + name + "\",\"value\":\""+ value + "\"}]"
        # endpoint_id is the endpoint = the device (shutter in this case) to open.
        str_request = self.cmd_prefix + "PUT /devices/{}/endpoints/{}/data HTTP/1.1\r\nContent-Length: ".format(str(endpoint_id),str(endpoint_id))+str(len(body))+"\r\nContent-Type: application/json; charset=UTF-8\r\nTransac-Id: 0\r\n\r\n"+body+"\r\n\r\n"
        a_bytes = bytes(str_request, "ascii")
        await self.connection.send(a_bytes)
        self.logger.debug('PUT request send to Websocket !')
        return 0

    # Run scenario
    async def put_scenarios(self, scenario_id):
        body=""
        # scenario_id is the id of scenario got from the get_scenarios command
        str_request = self.cmd_prefix + "PUT /scenarios/{} HTTP/1.1\r\nContent-Length: ".format(str(scenario_id))+str(len(body))+"\r\nContent-Type: application/json; charset=UTF-8\r\nTransac-Id: 0\r\n\r\n"+body+"\r\n\r\n"
        a_bytes = bytes(str_request, "ascii")
        await self.connection.send(a_bytes)
        # name = await websocket.recv()
        # parse_response(name)




    async def receiveMessage(self):
        '''
            Receiving all server messages and handling them
        '''
        while True:

            bytes_str = await self.connection.recv()
            # self.logger.debug(">>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>")
            # self.logger.debug(bytes_str)
            first = str(bytes_str[:40]) # Scanning 1st characters
            #Notify systemd watchdog
            await self.notify_alive()


            try:
                if ("refresh" in first):
                    self.logger.debug('OK refresh message detected !')
                    try:
                        pass
                        #ish('homeassistant/sensor/tydom/last_update', str(datetime.fromtimestamp(time.time())), qos=1, retain=True)
                    except:
                        self.logger.error(">>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>")
                        self.logger.error('RAW INCOMING :')
                        self.logger.error(bytes_str)
                        self.logger.error('END RAW')
                        self.logger.error(">>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>")
                elif ("PUT /devices/data" in first):
                    self.logger.debug('PUT /devices/data message detected !')
                    try:
                        incoming = self.parse_put_response(bytes_str)
                        # self.logger.debug(">>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>")
                        await self.parse_response(incoming)
                        # self.logger.debug('PUT message processed !')
                        # self.logger.debug("##################################")
                        #ish('homeassistant/sensor/tydom/last_update', str(datetime.fromtimestamp(time.time())), qos=1, retain=True)
                    except:
                        self.logger.error(">>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>")
                        self.logger.error('RAW INCOMING :')
                        self.logger.error(bytes_str)
                        self.logger.error('END RAW')
                        self.logger.error(">>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>")
                elif ("scn" in first):
                    try:
                        # self.logger.debug(">>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>")
                        incoming = get(bytes_str)
                        await self.parse_response(incoming)
                        self.logger.debug('Scenarii message processed !')
                        self.logger.debug("##################################")
                    except:
                        self.logger.error(">>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>")
                        self.logger.error('RAW INCOMING :')
                        self.logger.error(bytes_str)
                        self.logger.error('END RAW')
                        self.logger.error(">>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>")            
                elif ("POST" in first):
                    try:
                        # self.logger.debug(">>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>")
                        incoming = self.parse_put_response(bytes_str)
                        await self.parse_response(incoming)
                        self.logger.debug('POST message processed !')
                        # self.logger.debug("##################################")
                    except:
                        self.logger.debug(">>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>")
                        self.logger.debug('RAW INCOMING :')
                        self.logger.debug(bytes_str)
                        self.logger.debug('END RAW')
                        self.logger.debug(">>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>")
                elif ("HTTP/1.1" in first): #(bytes_str != 0) and 
                    response = self.response_from_bytes(bytes_str[len(self.cmd_prefix):])
                    incoming = response.data.decode("utf-8")
                    # self.logger.debug(">>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>")
                    # self.logger.debug(">>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>")
                    # self.logger.debug(incoming)
                    # self.logger.debug(">>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>")
                    # self.logger.debug(">>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>")
                    try:
                        # self.logger.debug(">>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>")
                        await self.parse_response(incoming)
                        # self.logger.debug('Pong !')
                        # self.logger.debug("##################################")
                    except:
                        self.logger.debug(">>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>")
                        self.logger.debug('RAW INCOMING :')
                        self.logger.debug(bytes_str)
                        self.logger.debug('END RAW')
                        self.logger.debug(">>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>")
                        # await parse_put_response(incoming)
                else:
                    self.logger.debug("Didn't detect incoming type, here it is :")
                    self.logger.debug(">>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>")
                    self.logger.debug('RAW INCOMING :')
                    self.logger.debug(bytes_str)
                    self.logger.debug('END RAW')
                    self.logger.debug(">>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>")

            except Exception as e:
                self.logger.debug("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
                self.logger.debug('receiveMessage error')
                self.logger.debug(e)
                self.logger.debug('Exiting to ensure systemd restart....')
                sys.exit() #Exit all to ensure systemd restart
                # self.logger.debug(bytes_str)
                # self.logger.debug('Reconnecting in 8s')
                # await asyncio.sleep(8)
                # await self.connect()





    # Basic response parsing. Typically GET responses + instanciate covers and alarm class for updating data
    async def parse_response(self, incoming):
        data = incoming
        msg_type = None
        first = str(data[:40])
        
        # Detect type of incoming data
        if (data != ''):
            if ("id" in first):
                self.logger.debug(">>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>")
                self.logger.debug('Incoming message type : data detected')
                msg_type = 'msg_data'
            elif ("date" in first):
                self.logger.debug(">>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>")
                self.logger.debug('Incoming message type : config detected')
                msg_type = 'msg_config'
            elif ("doctype" in first):
                self.logger.debug('Incoming message type : html detected (probable 404)')
                msg_type = 'msg_html'
                self.logger.debug(data)
            elif ("productName" in first):
                self.logger.debug(">>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>")
                self.logger.debug('Incoming message type : Info detected')
                msg_type = 'msg_info'
                # self.logger.debug(data)        
            else:
                self.logger.debug("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
                self.logger.debug('Incoming message type : no type detected')
                self.logger.debug(first)

            if not (msg_type == None):
                try:
                    parsed = json.loads(data)
                    # self.logger.debug(parsed)
                    if (msg_type == 'msg_config'):
                        for i in parsed["endpoints"]:
                            # Get list of shutter
                            if i["last_usage"] == 'shutter':
                                # self.logger.debug('{} {}'.format(i["id_endpoint"],i["name"]))
                                device_dict[i["id_endpoint"]] = i["name"]
                                # TODO get other device type
                            if i["last_usage"] == 'alarm':
                                # self.logger.debug('{} {}'.format(i["id_endpoint"], i["name"]))
                                device_dict[i["id_endpoint"]] = "Tyxal Alarm"
                        self.logger.debug('Configuration updated')
                        
                    elif (msg_type == 'msg_data'):
                        for i in parsed:
                            attr = {}
                            if i["endpoints"][0]["error"] == 0:
                                for elem in i["endpoints"][0]["data"]:
                                    # Get full name of this id
                                    endpoint_id = i["endpoints"][0]["id"]
                                    # Element name
                                    elementName = elem["name"]
                                    # Element value
                                    elementValue = elem["value"]
                                    
                                    # Get last known position (for shutter)
                                    if elementName == 'position':
                                        name_of_id = self.get_name_from_id(endpoint_id)
                                        if len(name_of_id) != 0:
                                            print_id = name_of_id
                                        else:
                                            print_id = endpoint_id
                                        # self.logger.debug('{} : {}'.format(print_id, elementValue))
                                        new_cover = "cover_tydom_"+str(endpoint_id)
                                        new_cover = Cover(id=endpoint_id,name=print_id, current_position=elementValue, attributes=i, mqtt=self.mqtt_client)
                                        new_cover.update()

                                    # Get last known state (for alarm)
                                    if elementName in deviceAlarmKeywords:
                                        alarm_data = '{} : {}'.format(elementName, elementValue)
                                        # self.logger.debug(alarm_data)
                                        # alarmMode  : ON or ZONE or OFF
                                        # alarmState : ON = Triggered
                                        # alarmSOS   : true = SOS triggered
                                        state = None
                                        sos_state = False
                                        
                                        if alarm_data == "alarmMode : ON":
                                            state = "armed_away"
                                        elif alarm_data == "alarmMode : ZONE":
                                            state = "armed_home"
                                        elif alarm_data == "alarmMode : OFF":
                                            state = "disarmed"
                                        elif alarm_data == "alarmState : ON":
                                            state = "triggered"
                                        elif alarm_data == "alarmSOS : true":
                                            state = "triggered"
                                            sos_state = True
                                        else:
                                            attr[elementName] = [elementValue]
                                        #     attr[alarm_data]
                                            # self.logger.debug(attr)
                                        #device_dict[i["id_endpoint"]] = i["name"]
                                        if (sos_state == True):
                                            self.logger.debug("SOS !")
                                        if not (state == None):
                                            # self.logger.debug(state)
                                            alarm = "alarm_tydom_"+str(endpoint_id)
                                            # self.logger.debug("Alarm created / updated : "+alarm)
                                            alarm = Alarm(id=endpoint_id,name="Tyxal Alarm", current_state=state, attributes=attr, sos=str(sos_state), mqtt=self.mqtt_client)
                                            alarm.update()
                    elif (msg_type == 'msg_html'):
                        self.logger.debug("HTML Response ?")
                    elif (msg_type == 'msg_info'):
                        pass
                    else:
                        # Default json dump
                        self.logger.debug()
                        self.logger.debug(json.dumps(parsed, sort_keys=True, indent=4, separators=(',', ': ')))
                except Exception as e:
                    self.logger.debug("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")

                    self.logger.debug('Cannot parse response !')
                    # self.logger.debug('Response :')
                    # self.logger.debug(data)
                    if (e != 'Expecting value: line 1 column 1 (char 0)'):
                        self.logger.debug("Error : ", e)


    # PUT response DIRTY parsing
    def parse_put_response(self, bytes_str):
        # TODO : Find a cooler way to parse nicely the PUT HTTP response
        resp = bytes_str[len(self.cmd_prefix):].decode("utf-8")
        fields = resp.split("\r\n")
        fields = fields[6:]  # ignore the PUT / HTTP/1.1
        end_parsing = False
        i = 0
        output = str()
        while not end_parsing:
            field = fields[i]
            if len(field) == 0 or field == '0':
                end_parsing = True
            else:
                output += field
                i = i + 2
        parsed = json.loads(output)
        return json.dumps(parsed)

    ######### FUNCTIONS

    def response_from_bytes(self, data):
        sock = BytesIOSocket(data)
        response = HTTPResponse(sock)
        response.begin()
        return urllib3.HTTPResponse.from_httplib(response)

    def put_response_from_bytes(self, data):
        request = HTTPRequest(data)
        return request

    # Get pretty name for a device id
    def get_name_from_id(self, id):
        name = ""
        if len(device_dict) != 0:
            name = device_dict[id]
        return(name)

    # Generate 16 bytes random key for Sec-WebSocket-Keyand convert it to base64
    def generate_random_key(self):
        return base64.b64encode(os.urandom(16))

    # Build the headers of Digest Authentication
    def build_digest_headers(self, nonce):
        digestAuth = HTTPDigestAuth(self.mac, self.password)
        chal = dict()
        chal["nonce"] = nonce[2].split('=', 1)[1].split('"')[1]
        chal["realm"] = "ServiceMedia" if self.remote_mode is True else "protected area"
        chal["qop"] = "auth"
        digestAuth._thread_local.chal = chal
        digestAuth._thread_local.last_nonce = nonce
        digestAuth._thread_local.nonce_count = 1
        return digestAuth.build_digest_header('GET', "https://{}:443/mediation/client?mac={}&appli=1".format(self.host, self.mac))

    ###############################################################
    # Commands                                                    #
    ###############################################################

    # Get some information on Tydom
    async def get_info(self):
        msg_type = '/info'
        await self.send_message(self.connection, msg_type)

    # Refresh (all)
    async def post_refresh(self):
        if not (self.connection.open):
            self.logger.debug('Exiting to ensure systemd restart....')
            sys.exit() #Exit all to ensure systemd restart
        else:
            # self.logger.debug("Refresh....")
            msg_type = '/refresh/all'
            # req = 'POST'
            await self.send_post_message(self.connection, msg_type)

    # Get the moments (programs)
    async def get_moments(self):
        msg_type = '/moments/file'
        req = 'GET'
        await self.send_message(self.connection, msg_type)

    # Get the scenarios
    async def get_scenarii(self):
        msg_type = '/scenarios/file'
        req = 'GET'
        await self.send_message(self.connection, msg_type)


    # Get a ping (pong should be returned)
    async def get_ping(self):
        msg_type = 'ping'
        req = 'GET'
        await self.send_message(self.connection, msg_type)


    # Get all devices metadata
    async def get_devices_meta(self):
        msg_type = '/devices/meta'
        req = 'GET'
        await self.send_message(self.connection, msg_type)


    # Get all devices data
    async def get_devices_data(self):
        msg_type = '/devices/data'
        req = 'GET'
        await self.send_message(self.connection, msg_type)


    # List the device to get the endpoint id
    async def get_configs_file(self):
        msg_type = '/configs/file'
        req = 'GET'
        await self.send_message(self.connection, msg_type)

    async def get_data(self):
        if not self.connection.open:
            self.logger.debug('get_data error !')
            # await self.exiting()wait self.exiting()
            self.logger.debug('Exiting to ensure systemd restart....')
            sys.exit() #Exit all to ensure systemd restart

        else:
            await self.get_configs_file()
            await asyncio.sleep(2)
            await self.get_devices_data()

    # Give order to endpoint
    async def get_device_data(self, id):
        # 10 here is the endpoint = the device (shutter in this case) to open.
        str_request = self.cmd_prefix + "GET /devices/{}/endpoints/{}/data HTTP/1.1\r\nContent-Length: 0\r\nContent-Type: application/json; charset=UTF-8\r\nTransac-Id: 0\r\n\r\n".format(str(id),str(id))
        a_bytes = bytes(str_request, "ascii")
        await self.connection.send(a_bytes)
        # name = await websocket.recv()
        # parse_response(name)


    async def notify_alive(self, msg='OK'):
        statestr = msg #+' : '+str(datetime.fromtimestamp(time.time()))
        self.logger.debug("Tydom HUB is still connected, systemd's watchdog notified...")

        # await self.POST_Hassio(sensorname='last_ping', state=statestr, friendlyname='Tydom Connection')
        # except Exception as e:
        #     self.logger.debug('Hassio sensor down !'+e)

    async def exiting(self):

        self.logger.debug("Exiting to ensure systemd restart....")
        statestr = 'Exiting...'+' : '+str(datetime.fromtimestamp(time.time()))

        # try:
        #     await self.POST_Hassio(sensorname='last_ping', state=statestr, friendlyname='Tydom connection')
        # except Exception as e:
        #     self.logger.debug('Hassio sensor down !'+e)
        sys.exit()

class BytesIOSocket:
    def __init__(self, content):
        self.handle = BytesIO(content)

    def makefile(self, mode):
        return self.handle

class HTTPRequest(BaseHTTPRequestHandler):
    def __init__(self, request_text):
        #self.rfile = StringIO(request_text)
        self.raw_requestline = request_text
        self.error_code = self.error_message = None
        self.parse_request()

    def send_error(self, code, message):
        self.error_code = code
        self.error_message = message
