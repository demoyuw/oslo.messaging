#    Copyright 2015 Mirantis, Inc.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import abc
import logging
import time

import six

from oslo_messaging._drivers import common as rpc_common
from oslo_messaging._drivers.zmq_driver import zmq_address
from oslo_messaging._drivers.zmq_driver import zmq_async
from oslo_messaging._drivers.zmq_driver import zmq_names
from oslo_messaging._drivers.zmq_driver import zmq_socket
from oslo_messaging._i18n import _LE

LOG = logging.getLogger(__name__)

zmq = zmq_async.import_zmq()


class UnsupportedSendPattern(rpc_common.RPCException):

    """Exception to raise from publishers in case of unsupported
    sending pattern called.
    """

    def __init__(self, pattern_name):
        """Construct exception object

        :param pattern_name: Message type name from zmq_names
        :type pattern_name: str
        """
        errmsg = _LE("Sending pattern %s is unsupported.") % pattern_name
        super(UnsupportedSendPattern, self).__init__(errmsg)


@six.add_metaclass(abc.ABCMeta)
class PublisherBase(object):

    """Abstract publisher class

    Each publisher from zmq-driver client should implement
    this interface to serve as a messages publisher.

    Publisher can send request objects from zmq_request.
    """

    def __init__(self, sockets_manager):

        """Construct publisher

        Accept configuration object and Name Service interface object.
        Create zmq.Context and connected sockets dictionary.

        :param conf: configuration object
        :type conf: oslo_config.CONF
        """
        self.outbound_sockets = sockets_manager
        self.conf = sockets_manager.conf
        self.matchmaker = sockets_manager.matchmaker
        super(PublisherBase, self).__init__()

    @abc.abstractmethod
    def send_request(self, request):
        """Send request to consumer

        :param request: Message data and destination container object
        :type request: zmq_request.Request
        """

    def _send_request(self, socket, request):
        """Send request to consumer.
        Helper private method which defines basic sending behavior.

        :param socket: Socket to publish message on
        :type socket: zmq.Socket
        :param request: Message data and destination container object
        :type request: zmq_request.Request
        """
        LOG.debug("Sending %(type)s message_id %(message)s to a target "
                  "%(target)s",
                  {"type": request.msg_type,
                   "message": request.message_id,
                   "target": request.target})
        socket.send_pyobj(request)

    def cleanup(self):
        """Cleanup publisher. Close allocated connections."""
        self.outbound_sockets.cleanup()


class SocketsManager(object):

    def __init__(self, conf, matchmaker, listener_type, socket_type):
        self.conf = conf
        self.matchmaker = matchmaker
        self.listener_type = listener_type
        self.socket_type = socket_type
        self.zmq_context = zmq.Context()
        self.outbound_sockets = {}

    def _track_socket(self, socket, target):
        self.outbound_sockets[str(target)] = (socket, time.time())

    def _get_hosts_and_connect(self, socket, target):
        hosts = self.matchmaker.get_hosts(
            target, zmq_names.socket_type_str(self.listener_type))
        for host in hosts:
            socket.connect_to_host(host)
        self._track_socket(socket, target)

    def _check_for_new_hosts(self, target):
        socket, tm = self.outbound_sockets[str(target)]
        if 0 <= self.conf.zmq_target_expire <= time.time() - tm:
            self._get_hosts_and_connect(socket, target)
        return socket

    def get_socket(self, target):
        if str(target) in self.outbound_sockets:
            socket = self._check_for_new_hosts(target)
        else:
            socket = zmq_socket.ZmqSocket(self.conf, self.zmq_context,
                                          self.socket_type)
            self._get_hosts_and_connect(socket, target)
        return socket

    def get_socket_to_broker(self, target):
        socket = zmq_socket.ZmqSocket(self.conf, self.zmq_context,
                                      self.socket_type)
        self._track_socket(socket, target)
        address = zmq_address.get_broker_address(self.conf)
        socket.connect_to_address(address)
        return socket

    def cleanup(self):
        for socket, tm in self.outbound_sockets.values():
            socket.close()
