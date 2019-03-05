#!/usr/bin/env python3

import argparse         # Parsing command-line arguments
import logging          # Logging
import signal           # Signal managing
from time import sleep  # Sleeping
import socket           # TCP and UDP sockets
import select           # Poll socket for incoming data
import threading        # Multi-threading
import queue            # Queue to share data between threads


##
# Globals
##########
default_log_file = None         # Log messages will be printed to stdin
default_log_level = 'ERROR'

# Exit codes
err_ok = 0
err_arg = 1
err_socket = 2
err_user = 3
err_exit = 4

# Protocol
proto_tcp_helo = 'HELO {0} {1} {2}\n'   # HELO <screen_name> <IP> <Port>\n
proto_tcp_acpt = 'ACPT {0}\n'           # ACPT <SN1> <IP1> <PORT1>:<SN2> <IP2> <PORT2>:...:<SNn> <IPn> <PORTn>\n
proto_tcp_rjct = 'RJCT {0}\n'           # RJCT <screen_name>\n
proto_tcp_exit = 'EXIT\n'               # EXIT\n
proto_udp_join = 'JOIN {0} {1} {2}\n'   # JOIN <screen_name> <IP> <Port>\n
proto_udp_mesg = 'MESG {0}: {1}\n'      # MESG <screen_name>: <message>\n
proto_udp_exit = 'EXIT {0}\n'           # EXIT <screen_name>\n

# Signals
signals_to_names = dict((getattr(signal, n), n) for n in dir(signal) if n.startswith('SIG') and '_' not in n)

# Flags
run_flag = None


##
# Classes
##########
class MemD:
    """ Chat client main class.
    """

    def __init__(self, welcome_port, retries=10, sleep_time=0.2):
        """ Initialize instance variables.

            :param  welcome_port    Welcome TCP port of the YaChat membership server.
            :param  retries         Connection retries before quiting.
            :param  sleep_time      Time to pause in between loops in sec.
        """
        self.ip = None
        self.welcome_port = welcome_port
        self.s_welcome = None

        self.retries = retries
        self.sleep_time = sleep_time

    def create_tcp_server_socket(self, ip, port):
        """ Create a TCP server socket.

            :param  ip      IP of the TCP socket.
            :param  port    Port of the TCP socket.
            :return TCP socket object, or None if it was not possible to create the socket.
        """
        try:
            # Create an INET, STREAMing socket
            s_server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

            # Bind the socket to the givenIP, and port
            s_server.bind((ip, port))

            # Become a server socket
            s_server.listen(5)
        except OSError as e1:
            logging.error('Failed to create TCP server socket: {0}'.format(e1))
            try:
                s_server.shutdown(socket.SHUT_WR)
                s_server.close()
            except OSError as e2:
                logging.error('Could not properly close TCP server socket: {0}'.format(e2))
            return None

        return s_server

    def get_local_ip(self):
        """ Get the local IP of this machine.

            :return Local IP address of the machine, or None if the IP could not be found.
        """
        # Find server's IP address
        try:
            ip = socket.gethostbyname(socket.gethostname())
        except OSError as e1:
            logging.error('Could not obtain the local IP: {0}'.format(e1))
            ip = None

        return ip

    def run(self):
        """ Run.
        """
        # Get local IP
        self.ip = self.get_local_ip()
        if self.ip is None:
            logging.critical('Could not get local IP to open the TCP socket')
            exit(err_socket)

        # Create welcome socket
        self.s_welcome = self.create_tcp_server_socket()
        if self.s_welcome is None:
            logging.critical('Could not create the welcome TCP socket')
            exit(err_socket)

        while run_flag:
            # Accept connections from outside
            (s_client, ip_client) = self.s_welcome.accept()

            # Pass connection to server thread
            ct = Server(s_client)
            ct.run()


class Server(threading.Thread):
    """ Server thread class.
    """
    
    def __init__(self, s_client, ip_client):
        """ Constructor.
        """
        self.s_client = s_client
        self.ip_client = ip_client
        
    def run(self):
        """ Run.
        """
        pass


##
# Entry point
##############
if __name__ == '__main__':
    # Parse command-line arguments
    parser = argparse.ArgumentParser(description='YaChat MemD membership daemon server.')

    parser.add_argument('welcome_port', type=int, help='Welcome TCP port of YaChat server.')
    parser.add_argument('-f', '--log-file', help='Log file path. Log will print to stdin by default.')
    parser.add_argument('-l', '--log-level', help='Verbosity level of the logger. Uses ERROR by default.')

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

    logging.basicConfig(format="%(asctime)s %(levelname)s:%(processName)s:%(threadName)s:%(funcName)s: %(message)s",
                        filename=args.log_file, level=log_level)

    logging.debug('Arguments: {0}'.format(args))

    # Create, set up signal handler and run Chatter object
    memd = MemD(args.welcome_port)
    memd.run()

    exit(err_ok)
