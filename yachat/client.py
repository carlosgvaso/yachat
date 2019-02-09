#!/usr/bin/env python3

import argparse     # Parsing command-line arguments
import logging      # Logging
#from sys import exit

import socket

# from _thread import *
import threading


##
# Globals
##########
default_log_file = None         # Log messages will be printed to stdin
default_log_level = 'INFO'

err_ok = 0
err_arg = 1


##
# Classes
##########
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

        logging.debug('Initial Chatter configuration:\n\tchat_server = {0}\n\tclients = {1}'
                      .format(self.chat_server, self.clients))

    def run(self):
        """ Run Chatter client.
        """
        logging.debug('Starting Chatter...')


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


##
# Entry point
##############
if __name__ == '__main__':
    # Parse command-line arguments
    parser = argparse.ArgumentParser(description='YaChat Chatter client.')

    parser.add_argument('screen_name', help='Screen name of chat user.')
    parser.add_argument('server_hostname', help='Hostname of chat server.')
    parser.add_argument('server_port', type=int, help='Port of chat server.')
    parser.add_argument('-f', '--log-file', help='Log file path.')
    parser.add_argument('-l', '--log-level', help='Verbosity level of the logger.')

    args = parser.parse_args()

    # Set up logger
    if not args.log_file:
        args.log_file = default_log_file
    if not args.log_level:
        args.log_level = default_log_level

    log_level = getattr(logging, args.log_level.upper(), args.log_level.upper())
    if not isinstance(log_level, int):
        logging.critical('Wrong log level provided: {0}'.format(args.log_level))
        exit(err_arg)

    logging.basicConfig(format="%(asctime)s %(levelname)s:%(module)s:%(funcName)s: %(message)s",
                        filename=args.log_file, level=log_level)

    logging.debug('Arguments: {0}'.format(args))

    # Create and run Chatter object
    chatter = Chatter(args.screen_name, args.server_hostname, args.server_port)
    chatter.run()

    exit(err_ok)
