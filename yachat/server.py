#!/usr/bin/env python3

import argparse         # Parsing command-line arguments
import logging          # Logging
import signal           # Signal managing
import socket           # TCP and UDP sockets
import select           # Poll socket for incoming data
import threading        # Multi-threading
#import queue            # Queue to share data between threads
#from time import sleep  # Sleeping


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
        logging.info('Server welcome port: {0}'.format(self.welcome_port))

        self.clients = dict()   # Client dict in the format: {'screen_name': {'ip': 'X.X.X.X', 'udp_port': X}, ...}
        self.clients_lock = threading.Lock()

        global run_flag
        run_flag = True  # Global flag

        self.retries = retries
        self.sleep_time = sleep_time

    def create_tcp_server_socket(self):
        """ Create a TCP server socket.

            :returns    TCP socket object, or None if it was not possible to create the socket.
        """
        logging.debug('Creating server TCP socket at {0}:{1}...'.format(self.ip, self.welcome_port))
        try:
            # Create an INET, STREAMing socket
            s_server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

            # Bind the socket to the givenIP, and port
            s_server.bind((self.ip, self.welcome_port))

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

        logging.debug('Server TCP socket successfully created!')
        return s_server

    def get_local_ip(self):
        """ Get the local IP of this machine.

            :returns    Local IP address of the machine, or None if the IP could not be found.
        """
        # Find server's IP address
        try:
            ip = socket.gethostbyname(socket.gethostname())
        except OSError as e1:
            logging.error('Could not obtain the local IP: {0}'.format(e1))
            ip = None

        logging.debug('Local IP: {0}'.format(ip))
        return ip

    def run(self):
        """ Run.
        """
        global run_flag

        # Get local IP
        logging.info('Getting local IP...')
        self.ip = self.get_local_ip()
        if self.ip is None:
            logging.critical('Could not get local IP to open the TCP socket')
            run_flag = False
            exit(err_socket)
        logging.info('Local IP: {0}'.format(self.ip))

        # Create welcome socket
        logging.info('Creating welcome socket...')
        self.s_welcome = self.create_tcp_server_socket()
        if self.s_welcome is None:
            logging.critical('Could not create the welcome TCP socket')
            run_flag = False
            exit(err_socket)

        logging.debug('run_flag = {0}'.format(run_flag))
        logging.info('Accepting connections...')
        while run_flag:
            # Accept connections from outside
            (s_client, ip_client) = self.s_welcome.accept()
            logging.info('New connection accepted from host at: {0}'.format(ip_client))

            # Pass connection to server thread
            logging.info('Passing client to servant thread...')
            st = Servant(s_client, self.clients, self.clients_lock)
            st.run()
        logging.debug('run_flag = {0}'.format(run_flag))
        logging.info('Shutting down...')


class Servant(threading.Thread):
    """ Servant thread class.
    """
    
    def __init__(self, client_socket, clients_dict, clients_lock):
        """ Constructor.

            :param  client_socket   Client TCP socket object.
            :param  clients_dict    Shared list of clients in the server.
            :param  clients_lock    Lock object for the shared clients list.
        """
        self.s_client = client_socket
        self.c_shared_dict = clients_dict
        self.c_lock = clients_lock

        self.msg_leftovers_tcp = bytes()    # If we receive the beginning of the next msg, save it here

    def close_tcp_connection(self):
        """ Safely close TCP socket connection.

            :returns    True if the connection was safely closed, False otherwise.
        """
        try:
            self.s_client.shutdown(socket.SHUT_WR)
            self.s_client.close()
        except (OSError, InterruptedError, RuntimeError) as e1:
            logging.error('Could not close TCP socket connection: {0}'.format(e1))
            return False
        return True

    def process_helo_msg(self):
        """ Receive and process the HELO message from the client.

            :returns    A tuple containing the screen name, IP and port of the client in that order, or None.
        """
        # Listen for the HELO response
        logging.debug('Listening for HELO message...')
        try:
            response = self.receive_tcp_msg()
        except (OSError, InterruptedError, RuntimeError) as e1:
            logging.error('Failed to get HELO response: {0}'.format(e1))
            response = bytes()
        logging.debug('Received: {0}'.format(response))

        # Process response
        logging.debug('Processing HELO message...')
        if b'HELO' in response:
            try:
                words = str(response.decode(encoding='utf-8')).strip('HELO ').rstrip('\n').split(' ')
                logging.debug('words = {0}'.format(words))
                screen_name = words[0]
                client_ip = words[1]
                client_port = words[2]
            except Exception as e1:
                logging.warning('Could not process the HELO message: {0}'.format(e1))
                screen_name = None
                client_ip = None
                client_port = None
        else:
            logging.warning('Did not received HELO message: {0}'.format(e1))
            screen_name = None
            client_ip = None
            client_port = None

        logging.debug('screen_name = {0}, client_ip = {1}, client_port = {2}'.format(screen_name, client_ip, client_port))
        return screen_name, client_ip, client_port

    def receive_tcp_msg(self):
        """ Receive message over TCP socket.

            :returns    Message received as a bytes object.
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

        while receiving and run_flag:
            ready = select.select([self.s_client], [], [], 0.5)[0]
            if ready:
                chunk = self.s_client.recv(2048)

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

    def run(self):
        """ Run.
        """
        logging.info('Servant started running...')

        # Process HELO
        logging.info('Processing HELO msg...')
        (c_name, c_ip, c_port) = self.process_helo_msg()

        # Validate new client, and add it to client list if we got a proper HELO msg
        if c_name and c_ip and c_port:
            logging.info('Validating screen name...')
            c_dict = self.validate_client(c_name, c_ip, c_port)
        else:
            c_dict = None

        # If dict is not empty send acceptance, else reject
        if c_dict:
            # Send ACPT msg
            logging.info('Sending ACPT msg...')
            self.send_acpt_msg(c_dict)
        else:
            # Send RJCT msg
            logging.info('Sending RJCT msg...')
            self.send_rjct_msg(c_name)

            # Close socket and return
            logging.info('Closing TCP connection and exiting thread...')
            self.close_tcp_connection()
            return

        #while run_flag:
        #    # Block the socket
        #    pass
        # Close TCP connection and return
        self.close_tcp_connection()
        return

    def send_acpt_msg(self, clients_dict):
        """ Send ACPT message to client.
        
            :param      clients_dict    Dictionary of all the clients in the room.
            :returns    True if the message was sent, False otherwise.
        """
        clients_str = str()
        for client_name in clients_dict:
            clients_str += '{0} {1} {2}:'.format(client_name,
                                                 clients_dict.get(client_name, {'ip': None}).get('ip', 'None'),
                                                 clients_dict.get(client_name, {'udp_port': None}).
                                                 get('udp_port', 'None'))

        msg = bytes(proto_tcp_acpt.format(clients_str.rstrip(':')).encode(encoding='utf-8'))
        logging.debug('msg = {0}'.format(msg))

        try:
            self.send_tcp_msg(msg)
        except (OSError, InterruptedError, RuntimeError) as e1:
            logging.error('Could not sent ACPT message: {0}'.format(e1))
            return False
        return True

    def send_rjct_msg(self, client_name):
        """ Send RJCT message to client.

            :param      client_name Client's screen name.
            :returns    True if the message was sent, False otherwise.
        """
        msg = bytes(proto_tcp_rjct.format(client_name).encode(encoding='utf-8'))
        logging.debug('msg = {0}'.format(msg))

        try:
            self.send_tcp_msg(msg)
        except (OSError, InterruptedError, RuntimeError) as e1:
            logging.error('Could not sent RJCT message: {0}'.format(e1))
            return False
        return True

    def send_tcp_msg(self, msg):
        """ Send message over TCP socket.

            :param      msg     Bytes object to send.
            :returns    Length in bytes of the message sent.
        """
        logging.debug('msg: {0}'.format(msg))
        msg_len = len(msg)
        logging.debug('msg_len: {0}'.format(msg_len))
        msg_sent = 0

        while msg_sent < msg_len:
            sent = self.s_client.send(msg[msg_sent:])
            if sent == 0:
                raise RuntimeError("Socket connection broken")
            msg_sent += sent

            logging.debug('msg_sent: {0}'.format(msg_sent))

        return msg_sent

    def validate_client(self, screen_name, client_ip, client_port):
        """ Validate screen name, and insert it into the clients dict.

            :param      screen_name Client screen name.
            :param      client_ip   Client IP address.
            :param      client_port Client UDP port.
            :returns    Return the clients dictionary if the screen name is valid, or None otherwise.
        """
        c_valid = None
        # Acquire the lock to the clients list
        logging.debug('Acquiring lock...')
        self.c_lock.acquire()
        try:
            # Check if the client is on the dict
            if screen_name not in self.c_shared_dict:
                logging.debug('Screen name not in the dict: {0}'.format(screen_name))
                # Insert new client, and return a copy of the dict
                self.c_shared_dict[screen_name] = {'ip': client_ip, 'udp_port': client_port}
                c_valid = self.c_shared_dict.copy()
        except Exception as e1:
            logging.error('Could not insert the client in the dict: {0}'.format(e1))
            c_valid = None
        finally:
            # Make sure we release the lock no matter what
            logging.debug('Releasing lock...')
            self.c_lock.release()

        logging.debug('c_valid = {0}'.format(c_valid))
        return c_valid


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
