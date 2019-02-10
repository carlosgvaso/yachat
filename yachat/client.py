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
default_log_level = 'WARN'

# Exit codes
err_ok = 0
err_arg = 1
err_join = 2

# Protocol
proto_tcp_helo = 'HELO {0} {1} {2}\n'   # HELO <screen_name> <IP> <Port>\n
proto_tcp_acpt = 'ACPT {0}\n'           # ACPT <SN1> <IP1> <PORT1>:<SN2> <IP2> <PORT2>:...:<SNn> <IPn> <PORTn>\n
proto_tcp_rjct = 'RJCT {0}\n'           # RJCT <screen_name>\n
proto_tcp_exit = 'EXIT\n'               # EXIT\n
proto_udp_join = 'JOIN {0} {1} {2}\n'   # JOIN <screen_name> <IP> <Port>\n
proto_udp_mesg = 'MESG {0}: {1}\n'      # MESG <screen_name>: <message>\n
proto_udp_exit = 'EXIT {0}\n'           # EXIT <screen_name>\n


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

        # Sockets
        self.s_server_tcp = None
        self.s_server_udp = None

        self.msg_leftovers_tcp = bytes()    # If we receive the beginning of the next msg, save it here

        logging.debug('Initial Chatter configuration:\n\tchat_server = {0}\n\tclients = {1}'
                      .format(self.chat_server, self.clients))

    def create_udp_port(self):
        """ Create UDP port to talk to other clients.

            TODO: implement method.
        """
        self.clients[0]['ip'] = 'localhost'
        self.clients[0]['udp_port'] = 8800

    def exit_server(self):
        """ Exit chat server.

            Must be run after Chatter.join_server().

            TODO:
                - Confirm exit using server's UDP exit confirmation.
                - Check the socket exists and it is connected.
        """
        logging.info('Exiting server...')

        msg = bytes(proto_tcp_exit.encode(encoding='utf-8'))
        logging.debug('msg = {0}'.format(msg))

        self.send_tcp_msg(self.s_server_tcp, msg)

        #self.s_server_tcp.shutdown()
        self.s_server_tcp.close()

    def join_server(self):
        """ Join chat server.

            Must be run after Chatter.create_udp_port().

            :return True if successful joining the server, False otherwise.
        """
        logging.info('Joining the chat membership server...')

        # create an INET, STREAMing socket, and connect to the chat server
        self.s_server_tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.s_server_tcp.connect((self.chat_server['hostname'], self.chat_server['welcome_port']))

        msg = bytes(proto_tcp_helo
                    .format(self.clients[0]['screen_name'], self.clients[0]['ip'], self.clients[0]['udp_port'])
                    .encode(encoding='utf-8'))
        logging.debug('msg = {0}'.format(msg))
        self.send_tcp_msg(self.s_server_tcp, msg)

        # Receive ACPT or RJCT message
        response = self.receive_tcp_msg(self.s_server_tcp)
        logging.debug('response: {0}'.format(response))

        # Process response
        if b'ACPT' in response:
            logging.info('Membership server accepted connection with screen name: {}'
                         .format(self.clients[0]['screen_name']))
            self.process_client_list(response)
        elif b'RJCT' in response:
            logging.warning('Membership server rejected connection with screen name: {}'
                            .format(self.clients[0]['screen_name']))
            self.request_new_screen_name()
            return False

        return True

    def process_client_list(self, response_str):
        """ Process client list from ACPT message to self.clients list.

            This method also checks the server returned the correct info for this client. If it does not, the connection
            is closed, and the client exits with err_join.

            :param  response_str    Full ACPT message.
        """
        # Remove everything except the list of clients, and separate the message into individual client info
        logging.debug('response_str = {0}'.format(response_str))
        client_list = str(response_str.decode(encoding='utf-8')).strip('ACPT ').rstrip('\n').split(':')
        logging.debug('client_list = {0}'.format(client_list))

        # Add each client to the clients structure
        for client in client_list:
            client_info = client.split(' ')
            client_info[2] = int(client_info[2])
            logging.debug('client_info = {0}'.format(client_info))

            # Check if this is the info for this client or another client
            if client_info[0] == self.clients[0]['screen_name']:
                # Confirm IP and UDP port
                if client_info[1] != self.clients[0]['ip'] or client_info[2] != self.clients[0]['udp_port']:
                    logging.error('Server has the wrong IP and/or port for this client')
                    self.exit_server()
                    exit(err_join)
                else:
                    logging.info('Server has the correct IP and port for this client')
            else:
                # Add new client to clients structure
                self.clients.append({'screen_name': client_info[0], 'ip': client_info[1], 'udp_port': client_info[2]})
                logging.debug('Added new client: {0}'.format(self.clients[-1]))

        logging.debug('self.clients = {0}'.format(self.clients))
        logging.info('Client list filled')

    def receive_tcp_msg(self, conn):
        """ Receive message over TCP socket.

            :param  conn    Socket connection.
            :return Message received as a bytes object.

            TODO: Make safe for faulty socket connection.
        """
        receiving = True

        # Check if last time we received data, we got the beginning of the next msg
        if self.msg_leftovers_tcp != b'':
            msg = bytes(self.msg_leftovers_tcp)
            self.msg_leftovers_tcp = None       # Clear the buffer for the next time

            # Check if we already got a whole second message last time
            if b'\n' in msg:
                receiving = False

                b_tmp = msg.split(b'\n')
                msg = b_tmp[0] + b'\n'
                self.msg_leftovers_tcp = b'\n'.join(b_tmp[1:])
        else:
            msg = bytes()

        while receiving:
            chunk = conn.recv(2048)

            if b'\n' in chunk:
                receiving = False

                b_tmp = chunk.split(b'\n')
                chunk = b_tmp[0] + b'\n'
                self.msg_leftovers_tcp = b'\n'.join(b_tmp[1:])
            elif chunk == b'':
                raise RuntimeError("Socket connection broken")

            msg += chunk
            logging.debug('chunk: {0}'.format(chunk))

        logging.debug('msg: {0}'.format(msg))
        logging.debug('msg_leftovers_tcp: {0}'.format(self.msg_leftovers_tcp))
        return msg

    def request_new_screen_name(self):
        """ Request new screen name from the user.
        """
        new_name = input('The screen name {0} is not available. Please, enter a new screen name: '.format(self.clients[0]['screen_name']))
        logging.debug('new_name = {0}'.format(new_name))

        self.clients[0]['screen_name'] = str(new_name)

    def run(self):
        """ Run Chatter client.
        """
        logging.info('Starting Chatter...')

        self.create_udp_port()

        joined_server = False
        while not joined_server:
            joined_server = self.join_server()

        self.exit_server()

    def send_tcp_msg(self, conn, msg):
        """ Send message over TCP socket.

            :param  conn    Socket connection.
            :param  msg     Bytes object to send.
            :return Length in bytes of the message sent.

            TODO: Make safe for faulty socket connection.
        """
        logging.debug('msg: {0}'.format(msg))
        msg_len = len(msg)
        logging.debug('msg_len: {0}'.format(msg_len))
        msg_sent = 0

        while msg_sent < msg_len:
            sent = conn.send(msg[msg_sent:])
            if sent == 0:
                raise RuntimeError("Socket connection broken")
            msg_sent += sent

            logging.debug('msg_sent: {0}'.format(msg_sent))

        return msg_sent


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
    parser.add_argument('-f', '--log-file', help='Log file path. Log will print to stdin by default.')
    parser.add_argument('-l', '--log-level', help='Verbosity level of the logger. Uses WARN by default.')

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
