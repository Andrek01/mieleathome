#!/usr/bin/env python3
# vim: set encoding=utf-8 tabstop=4 softtabstop=4 shiftwidth=4 expandtab
#########################################################################
#  Copyright 2020-      <AUTHOR>                                  <EMAIL>
#########################################################################
#  This file is part of SmartHomeNG.
#  https://www.smarthomeNG.de
#  https://knx-user-forum.de/forum/supportforen/smarthome-py
#
#  Sample plugin for new plugins to run with SmartHomeNG version 1.5 and
#  upwards.
#
#  SmartHomeNG is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  SmartHomeNG is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with SmartHomeNG. If not, see <http://www.gnu.org/licenses/>.
#
#########################################################################

from lib.model.smartplugin import *
from lib.item import Items

from .webif import WebInterface

import requests
import json
import time
import threading

import sys


# If a needed package is imported, which might be not installed in the Python environment,
# add it to a requirements.txt file within the plugin's directory


class mieleathome(SmartPlugin):
    """
    Main class of the Plugin. Does all plugin specific stuff and provides
    the update functions for the items
    """

    PLUGIN_VERSION = '1.0.0'    # (must match the version specified in plugin.yaml), use '1.0.0' for your initial plugin Release

    def __init__(self, sh):
        """
        Initalizes the plugin.

        If you need the sh object at all, use the method self.get_sh() to get it. There should be almost no need for
        a reference to the sh object any more.

        Plugins have to use the new way of getting parameter values:
        use the SmartPlugin method get_parameter_value(parameter_name). Anywhere within the Plugin you can get
        the configured (and checked) value for a parameter by calling self.get_parameter_value(parameter_name). It
        returns the value in the datatype that is defined in the metadata.
        """
        self.logger = logging.getLogger(__name__)
        self.sh = self.get_sh()
        self.items = Items.get_instance()
        self.auth = False
        self.AccesToken   = ''
        self.RefreshToken = ''
        self.Expiration = 0
        self.all_devices = {}
        self.miele_devices_by_deviceID = {}
        self.miele_devices_by_item = {}
        self.miele_device_by_action = {}
        
        # Call init code of parent class (SmartPlugin)
        super().__init__()

        # get the parameters for the plugin (as defined in metadata plugin.yaml):
        # self.param1 = self.get_parameter_value('param1')

        # cycle time in seconds, only needed, if hardware/interface needs to be
        # polled for value changes by adding a scheduler entry in the run method of this plugin
        # (maybe you want to make it a plugin parameter?)
        self.client_id =        self.get_parameter_value('miele_client_id')
        self.client_secret =    self.get_parameter_value('miele_client_secret')
        self.country =          self.get_parameter_value('miele_client_country')
        self._cycle =           self.get_parameter_value('miele_cycle')
        self.user =             self.get_parameter_value('miele_user')
        self.pwd =              self.get_parameter_value('miele_pwd')
        
        self.ValidFrom = ''         #Time and date when (new) tokens were received
        self.ValidThrough = ''      #Time and date when tokens will expire
        self.ValidFor = 0           #Timeframe in days for validity of tokens
        self.last_ping =""          #Time of last Ping from Event-Listener
        self.last_event_time  =""   #Time of last Event from Event-Listener
        self.last_event_action = {} #Last dict for event_action
        self.last_event_device = {} #Last dict for event_device
        
        self.Url='https://api.mcs3.miele.com'
        self.event_server   = None
        self.auth           = self._auth()

        # Initialization code goes here

        # On initialization error use:
        #   self._init_complete = False
        #   return

        # if plugin should start even without web interface
        self.init_webinterface(WebInterface)
        # if plugin should not start without web interface
        # if not self.init_webinterface():
        #     self._init_complete = False

        return

    def run(self):
        """
        Run method for the plugin
        """
        self.logger.debug("Run method called")
        # setup scheduler for device poll loop   (disable the following line, if you don't need to poll the device. Rember to comment the self_cycle statement in __init__ as well)
        if self.auth == True:
            self._getalldevices()
        
        self._getallDevices4Action()
        
        self.scheduler_add('poll_device', self.poll_device, cycle=self._cycle)
        
        self.alive = True
        self.event_server = miele_event(self.logger, self.Url, self.AccesToken, self)
        self.event_server.name = "mieleEventListener"
        
        # if you need to create child threads, do not make them daemon = True!
        # They will not shutdown properly. (It's a python bug)
        
        myTokenRefresh = (self.Expiration-100)
        self.scheduler_add('_refreshToken',self._refreshToken,cycle = myTokenRefresh)
        for device in self.miele_devices_by_deviceID:
            myPayload = self._getActions4Device(device)
            self._parseAction4Device(myPayload, device)
        self.event_server.start()
        
    def stop(self):
        """
        Stop method for the plugin
        """
        self.logger.debug("Stop method called")
        self.scheduler_remove('poll_device')
        self.scheduler_remove('_refreshToken')
        self.event_server.stop()
        self.alive = False

    
    def _getallDevices4Action(self):
        for ItemName in self.miele_devices_by_item:
            for Device in self.miele_device_by_action:
                if ItemName in Device:
                    self.miele_device_by_action[Device] = self.miele_devices_by_item[ItemName]
    def _auth(self):
        myHeaders = { "accept" : "application/json" }
        
        payload =  {"grant_type": "password",
                    "password" :self.pwd,
                    "username" : self.user,
                    "client_id" : self.client_id,
                    "client_secret":self.client_secret,
                    "vg" :self.country
                    }
        
        myResult = requests.post(self.Url+'/thirdparty/token/',data=payload,headers=myHeaders)
        try:
            if (myResult.status_code == 200):
                myRespPayload=json.loads(myResult.content.decode())
                self.AccesToken   = myRespPayload['access_token']
                self.RefreshToken = myRespPayload['refresh_token']
                self.Expiration = myRespPayload['expires_in']
                self.ValidFor = int(self.Expiration / 86400)                    #Timeframe in days for validity of tokens
                self.ValidFrom = time.ctime(time.time())                        #Time and date when (new) tokens were received
                self.ValidThrough = time.ctime(time.time() + self.Expiration)   #Time and date when tokens will expire
                return True
        except:
            self.logger.warning("Error while authentication on {}".format(self.Url+'/thirdparty/token/'))
        
        return False
    
    def _refreshToken(self):
        myHeaders = {
                "Authorization" : "Bearer {}".format(self.AccesToken),
                "Content-Type" : "application/x-www-form-urlencoded",
                "accept": "application/json"
                }
        payload = {
                    "client_id" : self.client_id,
                    "client_secret" : self.client_secret,
                    "refresh_token" : self.RefreshToken,
                    "grant_type" :"refresh_token"
                    }
        myResult = requests.post(self.Url+'/thirdparty/token/',data=payload,headers=myHeaders)
        try:    
            if (myResult.status_code == 200):
                myRespPayload=json.loads(myResult.content.decode())
                self.AccesToken   = myRespPayload['access_token']
                self.event_server.access_token = self.AccesToken 
                self.RefreshToken = myRespPayload['refresh_token']
                self.Expiration = myRespPayload['expires_in']
                myTokenRefresh = (self.Expiration-100)
                self.ValidFor = int(self.Expiration / 86400)                    #Timeframe in days for validity of tokens
                self.ValidFrom = time.ctime(time.time())                        #Time and date when (new) tokens were received
                self.ValidThrough = time.ctime(time.time() + self.Expiration)   #Time and date when tokens will expire
                self.scheduler_change('_refreshToken', cycle={myTokenRefresh:None}) # Zum Testen von 6 auf 10 Sekunden geändert
                #self.scheduler_remove('_refreshToken')
                #self.scheduler_add('_refreshToken',self._refreshToken,cycle = self.Expiration-100)
                self.auth = True
        except:
            self.logger.warning("Error while refresh Token on {}".format(self.Url+'/thirdparty/token/'))
            self.auth = False                    
    
    def _parseAction4Device(self,myPayload, deviceId):
        myItemParent = self.miele_devices_by_deviceID[deviceId]
        # Parse Payload to Items
        self._parseDict2Item(myPayload, myItemParent+'.actions')
        for entry in myPayload:
            myItem = self.items.return_item(myItemParent+'.actions.'+entry)
            if myItem != None:
                myItem(myPayload[entry])
        
        myItem = self.items.return_item(myItemParent+'.actions.processAction')
        if myItem != None:
            myAllowedValues= myItem()
            # Set allowed Action for processAction
            myActions = ['start','stop','pause','start_superfreezing','stop_superfreezing','start_supercooling','stop_supercooling']
            for i in range(1, 7):
                myItemName = myItemParent+'.visu.allowed_actions.'+myActions[i-1]
                myItem = self.items.return_item(myItemName)
                if i in myAllowedValues:
                    myItem(True)
                else:
                    myItem(False)
        
        
    def _getalldevices(self):
        myHeaders = {
                    "Authorization" : "Bearer {}".format(self.AccesToken)
                    }
        
        myUrl = self.Url + "/v1/devices?language={}".format(self.country[0:2])
        myResult = requests.get(myUrl,headers=myHeaders)
        try:
            if (myResult.status_code == 200):
                self.all_devices = json.loads(myResult.content.decode())
                self.logger.warning("Got all devices from Miele-Cloud - start parsing to Items")
                self._parseAllDevices(self.all_devices)
                self.logger.warning("Got all devices from Miele-Cloud - stopped parsing to Items")
            else:
                pass
        except err as Exception:
            self.all_devices = {}
            self.logger.warning("Error while getting devices from {}".format(myUrl))
    
    def _parseAllDevices(self,myPayload):
        ''' 
        !!! Change "type" to "device_type" in payload - shNG does not allow Items with Name "type" because its an attribute 
        '''
        myDummy = json.dumps(myPayload)
        myDummy = myDummy.replace('"type"','"device_type"')
        myPayload = json.loads(myDummy)
        
        for myDevice in myPayload:
            self._parseDict2Item(myPayload[myDevice],self.miele_devices_by_deviceID[myDevice])
    
    def _parseDict2Item(self, my_dict,my_item_path):
        for entry in my_dict:
            if type(my_dict[entry]) is dict:
                self._parseDict2Item(my_dict[entry],my_item_path+'.'+entry)
            else:
                if type(my_dict[entry]) is list :
                    if len(my_dict[entry]) > 0:
                        for myArrayEntry in my_dict[entry]:
                            if type(myArrayEntry) is dict:
                                self._parseDict2Item(myArrayEntry,my_item_path+'.'+entry)
                            else:
                                myItem = self.items.return_item(my_item_path+'.'+entry)
                                if (myItem != None):
                                    myItem(my_dict[entry])
                                #print (my_item_path+'.'+ entry +'=' + str(my_dict[entry]))
                else:
                    myItem = self.items.return_item(my_item_path+'.'+entry)
                    if (myItem != None):
                        myItem(my_dict[entry])
                    #print (my_item_path+'.'+ entry +'=' + str(my_dict[entry]))

    def _getActions4Device(self,deviceId):
    
    
        myHeaders = {
                    "Authorization" : "Bearer {}".format(self.AccesToken)
                    }
        
        myUrl = self.Url + "/v1/{}/actions".format(deviceId)
        myResult = requests.get(myUrl,headers=myHeaders)
        try:
            if (myResult.status_code == 200):
                myActions = json.loads(myResult.content.decode())
                self.logger.warning("Got all actions from Miele-Cloud for {} - start parsing to Items".format(deviceId))
                return myActions
        except err as Exception: 
            self.logger.warning("Error while getting Actions for Device :{}".format(deviceId))        
    
    def putCommand2Device(self,deviceID, myPayload):
        myHeaders = {
                    "Authorization" : "Bearer {}".format(self.AccesToken)
                    }
        
        myUrl = self.Url + "//devices/{}/actions".format(deviceID)
        myResult = requests.put(myUrl,headers=myHeaders,json=myPayload)
        
            
    def parse_item(self, item):
        """
        Default plugin parse_item method. Is called when the plugin is initialized.
        The plugin can, corresponding to its attribute keywords, decide what to do with
        the item in future, like adding it to an internal array for future reference
        :param item:    The item to process.
        :return:        If the plugin needs to be informed of an items change you should return a call back function
                        like the function update_item down below. An example when this is needed is the knx plugin
                        where parse_item returns the update_item function when the attribute knx_send is found.
                        This means that when the items value is about to be updated, the call back function is called
                        with the item, caller, source and dest as arguments and in case of the knx plugin the value
                        can be sent to the knx with a knx write function within the knx plugin.
        """
        if self.has_iattr(item.conf, 'miele_deviceid'):
            self.logger.debug("parse item: {}".format(item))
            self.miele_devices_by_deviceID[item.conf['miele_deviceid']] = item.path()
            self.miele_devices_by_item[item.path()] = item.conf['miele_deviceid']
            return self.update_item
        
        if self.has_iattr(item.conf, 'miele_command'):
            self.miele_device_by_action[item.path()] = ''
            return self.update_item  
        # todo
        # if interesting item for sending values:
        #   return self.update_item

    def parse_logic(self, logic):
        """
        Default plugin parse_logic method
        """
        if 'xxx' in logic.conf:
            # self.function(logic['name'])
            pass

    def update_item(self, item, caller=None, source=None, dest=None):
        """
        Item has been updated

        This method is called, if the value of an item has been updated by SmartHomeNG.
        It should write the changed value out to the device (hardware/interface) that
        is managed by this plugin.

        :param item: item to be updated towards the plugin
        :param caller: if given it represents the callers name
        :param source: if given it represents the source
        :param dest: if given it represents the dest
        """
        if self.alive and caller != self.get_shortname():
            # code to execute if the plugin is not stopped
            # and only, if the item has not been changed by this this plugin:
            self.logger.info("Update item: {}, item has been changed outside this plugin".format(item.id()))

            if self.has_iattr(item.conf, 'foo_itemtag'):
                self.logger.warning("update_item was called with item '{}' from caller '{}', source '{}' and dest '{}'".format(item,
                                                                                                                               caller, source, dest))
            if self.has_iattr(item.conf, 'miele_command'):
                deviceId = self.miele_device_by_action[item.path()]
                myPayload = json.loads(item.conf['miele_command'])
                self.putCommand2Device(deviceId, myPayload)
            pass

    def poll_device(self):
        """
        Polls for updates of the device

        This method is only needed, if the device (hardware/interface) does not propagate
        changes on it's own, but has to be polled to get the actual status.
        It is called by the scheduler which is set within run() method.
        """
        if self.auth == True:
            self._getalldevices()
        
        # # get the value from the device
        # device_value = ...
        #
        # # find the item(s) to update:
        # for item in self.sh.find_items('...'):
        #
        #     # update the item by calling item(value, caller, source=None, dest=None)
        #     # - value and caller must be specified, source and dest are optional
        #     #
        #     # The simple case:
        #     item(device_value, self.get_shortname())
        #     # if the plugin is a gateway plugin which may receive updates from several external sources,
        #     # the source should be included when updating the the value:
        #     item(device_value, self.get_shortname(), source=device_source_id)
        


class miele_event(threading.Thread):
    def __init__(self, logger, url, access_token, mieleathome):
        threading.Thread.__init__(self)
        self.logger = logger
        self.url  = url+ '/v1/devices/all/events'
        self.access_token = access_token
        self.request = None
        self.alive = False
        self.mieleathome = mieleathome
        self.last_event = ""
    
    def start(self):
        
        self.alive = True
        self.logger.info("mieleathome - starting Event-Listener")
        while self.alive == True:        
            try:
                myHeaders = {
                     "Authorization" : "Bearer {}".format(self.access_token),
                     "Accept": "text/event-stream",
                     "Accept-Language" : "de-DE",
                     "Connection": "Keep-Alive"
                    }
                self.response = requests.get('https://api.mcs3.miele.com/v1/devices/all/events',headers=myHeaders, stream=True)
                
                for line in self.response.iter_lines():
                    if line:
                        myPayload = line.decode()
                        
                        if ('event' in myPayload):
                            self.last_event = myPayload.split(":")[1].strip()
                            continue
                        elif 'ping' not in myPayload:
                            myPayload=json.loads(myPayload.split(":")[1].strip())
                            
                        if self.last_event == "ping":
                            self.last_event = ""
                            self.mieleathome.last_ping = time.ctime(time.time())
                            self.logger.warning("mieleathome - got Ping-Event :")
                        elif self.last_event == "devices":
                            self.logger.warning("mieleathome - got devices-Event :" + json.dumps(myPayload))
                            self.last_event = ""
                            self.mieleathome.last_event_device = time.ctime(time.time())
                            self.mieleathome._parseAllDevices(myPayload)
                        elif self.last_event == "actions":
                            self.logger.warning("mieleathome - got actions-Event :" + json.dumps(myPayload))
                            self.last_event = ""
                            self.mieleathome.last_event_action = time.ctime(time.time())
                            for device in myPayload:
                                self.mieleathome._parseAction4Device(myPayload[device], device)

            except Exception as err:
                # Happens when Internet-Connection was disconnted
                time.sleep(30)
                self.logger.warning("mieleathome - connection canceled - retry to get new Event-Connection")
                self.last_event = ''
                pass
                
    
        
        

    def stop(self):
        self.logger.info("mieleathome - stoping Event-Listener")
        self.alive = False
        self.response.close()
        
