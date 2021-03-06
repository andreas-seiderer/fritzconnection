"""
Module to communicate with the AVM Fritz!Box.
"""
# This module is part of the FritzConnection package.
# https://github.com/kbr/fritzconnection
# License: MIT (https://opensource.org/licenses/MIT)
# Author: Klaus Bremer


import os
import string
import requests

from .devices import DeviceManager
from .exceptions import FritzServiceError
from .soaper import Soaper

from .utils import HostnameVerificationAdapter

# FritzConnection defaults:
FRITZ_IP_ADDRESS = '169.254.1.1'
FRITZ_TCP_PORT = 49000
FRITZ_TCP_PORT_TLS = 49443
FRITZ_IGD_DESC_FILE = 'igddesc.xml'
FRITZ_TR64_DESC_FILE = 'tr64desc.xml'
FRITZ_USERNAME = 'dslf-config'


class FritzConnection:
    """
    Main class to set up a connection to the Fritz!Box router. All
    parameters are optional. `address` should be the ip of a router, in
    case that are multiple Fritz!Box routers in a network, the ip must
    be given. Otherwise it is undefined which router will respond. If
    `user` and `password` are not provided, the environment gets checked for
    FRITZ_USERNAME and FRITZ_PASSWORD settings and taken from there, if
    found.

    The optional parameter `timeout` is a floating number in seconds
    limiting the time waiting for a router response. This is a global
    setting for the internal communication with the router. In case of a
    timeout a `requests.ConnectTimeout` exception gets raised.
    (`New in version 1.1`)
    """

    def __init__(self, address=FRITZ_IP_ADDRESS, port=None, protocol='http', certificate=None,
                 user=None, password=None, timeout=None):
        """
        Initialisation of FritzConnection: reads all data from the box
        and also the api-description (the servicenames and according
        actionnames as well as the parameter-types) that can vary among
        models and stores these informations as instance-attributes.
        This can be an expensive operation. Because of this an instance
        of FritzConnection should be created once and reused in an
        application. All parameters are optional. But if there is more
        than one FritzBox in the network, an address (ip as string) must
        be given, otherwise it is not defined which box may respond. If
        no user is given the Environment gets checked for a
        FRITZ_USERNAME setting. If there is no entry in the environment
        the avm-default-username will be used. If no password is given
        the Environment gets checked for a FRITZ_PASSWORD setting. So
        password can be used without using configuration-files or even
        hardcoding. The optional parameter `timeout` is a floating
        number in seconds limiting the time waiting for a router
        response. This is a global setting for the internal
        communication with the router. In case of a timeout a
        `requests.ConnectTimeout` exception gets raised.
        """
        if user is None:
            user = os.getenv('FRITZ_USERNAME', FRITZ_USERNAME)
        if password is None:
            password = os.getenv('FRITZ_PASSWORD', '')

        self.session = requests.Session()  # session is shared for speed up (especially TLS)

        if port is None:
            if protocol == "http":
                port = FRITZ_TCP_PORT
            else:
                port = FRITZ_TCP_PORT_TLS
                self.session.mount('https://',
                                   HostnameVerificationAdapter(assert_hostname=False))  # disable hostname verification

        self.certificate = certificate

        self.soaper = Soaper(address, protocol, port, user, password, timeout=timeout, certificate=certificate,
                             session=self.session)
        self.device_manager = DeviceManager(timeout=timeout, certificate=self.certificate, session=self.session)

        descriptions = [FRITZ_IGD_DESC_FILE]
        if password:
            descriptions.append(FRITZ_TR64_DESC_FILE)
        for description in descriptions:
            source = f'{protocol}://{address}:{port}/{description}'
            try:
                self.device_manager.add_description(source)
            except OSError:
                # resource not available: ignore this
                pass

        self.device_manager.scan()
        self.device_manager.load_service_descriptions(address, protocol, port)

    def __repr__(self):
        """Return a readable representation"""
        return f"{self.modelname} at ip {self.soaper.address}\n" \
               f"FRITZ!OS: {self.system_version}"

    @property
    def services(self):
        """
        Dictionary of service instances. Keys are the service names.
        """
        return self.device_manager.services

    @property
    def modelname(self):
        """
        Returns the modelname of the router.
        """
        return self.device_manager.modelname

    @property
    def system_version(self):
        """
        Returns system version if known, otherwise None.
        """
        return self.device_manager.system_version

    @staticmethod
    def normalize_name(name):
        """
        Returns the normalized service name. E.g. WLANConfiguration and
        WLANConfiguration:1 will get converted to WLANConfiguration1.
        """
        if ':' in name:
            name, number = name.split(':', 1)
            name = name + number
        elif name[-1] not in string.digits:
            name = name + '1'
        return name

    # -------------------------------------------
    # public api:
    # -------------------------------------------

    def call_action(self, service_name, action_name, *,
                    arguments=None, **kwargs):
        """
        Executes the given action of the given service. Both parameters
        are required. Arguments are optional and can be provided as a
        dictionary given to 'arguments' or as separate keyword
        parameters. If 'arguments' is given additional
        keyword-parameters as further arguments are ignored.
        If the service_name does not end with a number (like 1), a 1
        gets added by default. If the service_name ends with a colon and a
        number, the colon gets removed. So i.e. WLANConfiguration
        expands to WLANConfiguration1 and WLANConfiguration:2 converts
        to WLANConfiguration2.
        Invalid service names will raise a ServiceError and invalid
        action names will raise an ActionError.
        """
        arguments = arguments if arguments else dict()
        if not arguments:
            arguments.update(kwargs)
        service_name = self.normalize_name(service_name)
        try:
            service = self.device_manager.services[service_name]
        except KeyError:
            raise FritzServiceError(f'unknown service: "{service_name}"')
        return self.soaper.execute(service, action_name, arguments)

    def reconnect(self):
        """
        Terminate the connection and reconnects with a new ip.
        """
        self.call_action('WANIPConn1', 'ForceTermination')
