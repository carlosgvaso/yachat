import socket

# from _thread import *
import threading

# import sys


class Chatter:
    """ Chat client main class.
    """

    def __init__(self, screen_name, server_hostname, server_welcome_port):
        """ Initialize instance variables.

            :param  screen_name         Username to register in the membership server.
            :param  server_hostname     Chat membership server's hostname.
            :param  server_welcome_port Welcome port of the chat membership server.
        """
        # Membership server info in the format:
        # { hostname, welcome_port }
        self.chat_server = {'hostname': server_hostname, 'welcome_port': server_welcome_port}

        # Clients info in the format:
        # [ { screen_name_0, ip_0, udp_port_0 }, { screen_name_1, ip_1, udp_port_1 }, ... ]
        #
        # The first entry is this instance of the client.
        self.clients = [{'screen_name': screen_name, 'ip': None, 'udp_port': None}]


class Listener (threading.Thread):
    """ Socket listener thread class.
    """

    def __init__(self, thread_id, name, socket_obj):
        """ Initialize instance variables.

            :param  thread_id   Thread's numeric ID.
            :param  name        Thread's name of the format "listener-<thread_id>".
            :param  socket_obj  Socket object to listen to.
        """
        threading.Thread.__init__(self)
        self.thread_id = thread_id  # Use socket port as the thread ID?
        self.name = name            # Of the format: listener-<thread_id>
        self.socket = socket_obj


class Reader (threading.Thread):
    """ Console reader thread class.
    """

    def __init__(self, thread_id, name):
        """ Initialize instance variables.

            :param  thread_id   Thread's numeric ID.
            :param  name        Thread's name of the format "reader-<thread_id>".
        """
        threading.Thread.__init__(self)
        self.thread_id = thread_id
        self.name = name            # of the format: reader-<thread_id>


class Sender (threading.Thread):
    """ Message sender thread class.
    """

    def __init__(self, thread_id, name, message):
        """ Initialize instance variables.

            :param  thread_id   Thread's numeric ID.
            :param  name        Thread's name of the format "sender-<thread_id>".
            :param  message     Message to be sent as a string.
        """
        threading.Thread.__init__(self)
        self.thread_id = thread_id  # Use socket port as the thread ID?
        self.name = name            # Of the format: sender-<thread_id>
        self.msg = message

    def run(self):
        """ Run.
        """
        # create an INET, STREAMing socket
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        # now connect to the web server on port 80 - the normal http port
        port = input("Port to connect to: ")
        s.connect(("127.0.0.1", port))
        msg = input("Type message: ")
        s.send(bytes(msg))
        msg_from_server = str(s.recv(2048))

        print("FROM SERVER: " + msg_from_server)
