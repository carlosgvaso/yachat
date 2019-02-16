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
err_join = 2
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
class Chatter:
    """ Chat client main class.
    """

    def __init__(self, screen_name, server_hostname, server_welcome_port, retries=10, sleep_time=0.2):
        """ Initialize instance variables.

            :param  screen_name         Username to register in the membership server.
            :param  server_hostname     Chat membership server's hostname.
            :param  server_welcome_port Welcome port of the chat membership server.
            :param  retries             Connection retries before quiting.
            :param  sleep_time          Time to pause in between loops in sec.
        """
        # Membership server info in the format:
        # { hostname, welcome_port }
        self.chat_server = {'hostname': server_hostname, 'welcome_port': server_welcome_port}

        # Clients info in the format:
        # [ { screen_name_0, ip_0, udp_port_0 }, { screen_name_1, ip_1, udp_port_1 }, ... ]
        #
        # The first entry is this instance of the client.
        self.clients = [{'screen_name': screen_name, 'ip': None, 'udp_port': None}]

        # Other data structures
        self.msg_leftovers_tcp = bytes()  # If we receive the beginning of the next msg, save it here
        self.q_listener = queue.Queue()  # Listener thread queue

        # Flags and signal handlers
        global run_flag
        run_flag = True            # Global flag
        self.original_sigint = None
        self.original_sigterm = None

        # Sockets
        self.s_server_tcp = None    # TCP port connected to the chat membership server
        self.s_server_udp = None    # UDP server port to listen for and send messages

        self.retries = retries              # Connection retries before quiting
        self.sleep_time = sleep_time        # Time to pause in between loops in sec

        logging.debug('Initial Chatter configuration:\n\tchat_server = {0}\n\tclients = {1}'
                      .format(self.chat_server, self.clients))

    def create_udp_socket(self):
        """ Create UDP socket to talk to other clients.

            :return True if success, False otherwise.
        """
        logging.info('Creating UDP socket...')
        # Find client's IP address
        try:
            self.clients[0]['ip'] = socket.gethostbyname(socket.gethostname())
        except OSError as e1:
            logging.error('Could not obtain the local IP: {0}'.format(e1))
            return False

        # Create a UDP socket
        try:
            self.s_server_udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.s_server_udp.setblocking(False)
            self.s_server_udp.bind((self.clients[0]['ip'], 0))
        except OSError as e1:
            logging.error('Could not create the UDP socket: {0}'.format(e1))
            return False

        # Save IP and port
        self.clients[0]['ip'], self.clients[0]['udp_port'] = self.s_server_udp.getsockname()
        logging.debug('UDP socket: ip = {0}, port = {1}'.format(self.clients[0]['ip'], self.clients[0]['udp_port']))

        return True

    def close_udp_socket(self):
        """ Safely close the UDP socket
        """
        logging.debug('Closing UDP socket...')
        try:
            self.s_server_udp.close()
        except OSError as e1:
            logging.error('Could not close the UDP socket: {0}'.format(e1))

    def exit_server(self):
        """ Exit chat server.

            Must be run after Chatter.join_server().
        """
        logging.info('Exiting server...')

        msg = bytes(proto_tcp_exit.encode(encoding='utf-8'))
        logging.debug('msg = {0}'.format(msg))

        try:
            self.send_tcp_msg(self.s_server_tcp, msg)
        except (OSError, InterruptedError, RuntimeError) as e1:
            logging.error('Could not properly exit the server: {0}'.format(e1))

        try:
            self.s_server_tcp.shutdown(socket.SHUT_WR)
            self.s_server_tcp.close()
        except OSError as e1:
            logging.error('Could not properly close the TCP socket: {0}'.format(e1))

    def exited_server(self, msg):
        """ Check we receive the EXIT message confirmation from the server.

            :param  msg Bytes object with the message from the server.
            :return True if the message was received, false otherwise
        """
        msg_str = str(msg.decode(encoding='utf-8'))

        if msg_str == proto_udp_exit.format(self.clients[0]['screen_name']):
            return True
        return False

    def join_server(self):
        """ Join chat server.

            Must be run after Chatter.create_udp_socket().

            :return True if successful joining the server, False otherwise.
        """
        logging.info('Joining the chat membership server...')

        # create TCP socket, and connect to the chat server
        try:
            self.s_server_tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.s_server_tcp.connect((self.chat_server['hostname'], self.chat_server['welcome_port']))
        except OSError as e1:
            logging.error('Failed to create TCP socket: {0}'.format(e1))
            try:
                self.s_server_tcp.shutdown(socket.SHUT_WR)
                self.s_server_tcp.close()
            except OSError as e2:
                logging.error('Could not properly close the TCP socket: {0}'.format(e2))
            return False
        except ConnectionRefusedError as e1:
            logging.error('Failed to connect to server: {0}'.format(e1))
            try:
                self.s_server_tcp.shutdown(socket.SHUT_WR)
                self.s_server_tcp.close()
            except OSError as e2:
                logging.error('Could not properly close the TCP socket: {0}'.format(e2))
            return False
        except InterruptedError as e1:
            logging.error('Connection to server interrupted: {0}'.format(e1))
            try:
                self.s_server_tcp.shutdown(socket.SHUT_WR)
                self.s_server_tcp.close()
            except OSError as e2:
                logging.error('Could not properly close the TCP socket: {0}'.format(e2))
            return False

        msg = bytes(proto_tcp_helo
                    .format(self.clients[0]['screen_name'], self.clients[0]['ip'], self.clients[0]['udp_port'])
                    .encode(encoding='utf-8'))
        logging.debug('msg = {0}'.format(msg))
        try:
            self.send_tcp_msg(self.s_server_tcp, msg)
        except (OSError, InterruptedError, RuntimeError) as e1:
            logging.error('Could not sent HELO message: {0}'.format(e1))
            try:
                self.s_server_tcp.shutdown(socket.SHUT_WR)
                self.s_server_tcp.close()
            except OSError as e2:
                logging.error('Could not properly close the TCP socket: {0}'.format(e2))
            return False

        # Receive ACPT or RJCT message
        try:
            response = self.receive_tcp_msg(self.s_server_tcp)
            logging.debug('response: {0}'.format(response))
        except (OSError, InterruptedError, RuntimeError) as e1:
            logging.error('Did not received HELO response: {0}'.format(e1))
            try:
                self.s_server_tcp.shutdown(socket.SHUT_WR)
                self.s_server_tcp.close()
            except OSError as e2:
                logging.error('Could not properly close the TCP socket: {0}'.format(e2))
            return False

        # Process response
        if b'ACPT' in response:
            logging.info('Membership server accepted connection with screen name: {}'
                         .format(self.clients[0]['screen_name']))
            self.process_client_list(response)
        elif b'RJCT' in response:
            logging.warning('Membership server rejected connection with screen name: {}'
                            .format(self.clients[0]['screen_name']))
            try:
                self.s_server_tcp.shutdown(socket.SHUT_WR)
                self.s_server_tcp.close()
            except OSError as e2:
                logging.error('Could not properly close the TCP socket: {0}'.format(e2))

            self.request_new_screen_name()
            return False
        else:
            logging.error('Received unknown message: {0}'.format(response))
            try:
                self.s_server_tcp.shutdown(socket.SHUT_WR)
                self.s_server_tcp.close()
            except OSError as e2:
                logging.error('Could not properly close the TCP socket: {0}'.format(e2))
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
                    global run_flag
                    run_flag = False
                    #self.stop(signal.SIGTERM)
                    return
                else:
                    logging.info('Server has the correct IP and port for this client')
                    print('{0} accepted to the chatroom'.format(self.clients[0]['screen_name']))
            else:
                # Add new client to clients structure
                self.clients.append({'screen_name': client_info[0], 'ip': client_info[1], 'udp_port': client_info[2]})
                logging.debug('Added new client: {0}'.format(self.clients[-1]))
                print('{0} is in the chatroom'.format(client_info[0]))

        logging.debug('self.clients = {0}'.format(self.clients))
        logging.info('Client list filled')

    def process_exit_message(self, msg_list):
        """ Process UDP EXIT message.

            Remove the client that exited from the clients data structure.

            :param  msg_list    List of space separated words of 'EXIT' message.
        """
        # Check we got the right message type
        if msg_list[0] != 'EXIT':
            logging.error('Wrong message type received for processing: {0}'.format(msg_list))
            return

        client_exited = msg_list[1]

        # Remove client
        for client in self.clients:
            if client_exited == client['screen_name']:
                self.clients.remove(client)
                logging.info('Client {0} left the server'.format(client['screen_name']))
                print('{0} left the chatroom'.format(client['screen_name']))
                logging.debug('self.clients = {0}'.format(self.clients))

    def process_join_message(self, msg_list):
        """ Process UDP JOIN message.

            Get the information of the new client, and add it to the clients data structure if the client is not this
            instance. If it is this instance, check that the information is corect.

            :param  msg_list    List of space separated words of 'JOIN' message.
        """
        # Check we got the right message type
        if msg_list[0] != 'JOIN':
            logging.error('Wrong message type received for processing: {0}'.format(msg_list))
            return

        msg_list[3] = int(msg_list[3])  # Convert the port number to int

        # Check if this client is the one that joined
        if msg_list[1] == self.clients[0]['screen_name']:
            if msg_list[2] != self.clients[0]['ip'] or msg_list[3] != self.clients[0]['udp_port']:
                logging.error('Server has the wrong IP and/or port for this client')
                self.stop(signal.SIGTERM)
                return
            else:
                logging.info('Server has the correct IP and port for this client')
        else:
            # Add new client to clients data structure
            self.clients.append({'screen_name': msg_list[1], 'ip': msg_list[2], 'udp_port': msg_list[3]})
            logging.debug('Added new client: {0}'.format(self.clients[-1]))
            logging.info('Client {0} joined the server'.format(msg_list[1]))
            print('{0} joined the chatroom'.format(msg_list[1]))

    def process_mesg_message(self, msg_list):
        """ Process UDP MESG message.

            :param  msg_list    List of space separated words of 'MESG' message.
        """
        # Check we got the right message type
        if msg_list[0] != 'MESG':
            logging.error('Wrong message type received for processing: {0}'.format(msg_list))
            return

        logging.info('Message received: {0} {1}'.format(msg_list[1], msg_list[2]))
        print('{0} {1}'.format(msg_list[1], msg_list[2]))

    def process_udp_messages(self, msg):
        """ Process messages received over UDP.

            :param  msg Message received as a bytes object.
        """
        # Convert message to a string, and split on white spaces
        msg_list = str(msg.decode(encoding='utf-8')).rstrip('\n').split(' ')

        # Select the function to use for the message type
        if msg_list[0] == 'JOIN':
            self.process_join_message(msg_list)
        elif msg_list[0] == 'EXIT':
            self.process_exit_message(msg_list)
        elif msg_list[0] == 'MESG':
            self.process_mesg_message(msg_list)
        else:
            logging.error('Unknown UDP message received: {}'.format(msg))

    def receive_tcp_msg(self, conn):
        """ Receive message over TCP socket.

            :param  conn    TCP socket connection.
            :return Message received as a bytes object.
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
            ready = select.select([self.s_server_tcp], [], [], 0.5)[0]
            if ready:
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
        logging.debug('msg_leftovers_udp: {0}'.format(self.msg_leftovers_tcp))
        return msg

    def request_new_screen_name(self):
        """ Request new screen name from the user.
        """
        try:
            new_name = input('The screen name {0} is not available. Please, enter a new screen name: '
                             .format(self.clients[0]['screen_name']))
        except EOFError:
            print()
            logging.warning('Ctrl+D input detected. Sending exit signal...')
            global run_flag
            run_flag = False
            #self.stop(signal.SIGTERM)
            return

        logging.debug('new_name = {0}'.format(new_name))

        self.clients[0]['screen_name'] = str(new_name)

    def run(self):
        """ Run Chatter client.
        """
        logging.info('Starting Chatter...')
        global run_flag

        count = 0
        created_socket = False
        while not created_socket and count < self.retries and run_flag:
            count += 1
            logging.debug('Tries: {0}'.format(count))

            created_socket = self.create_udp_socket()

            # Do nothing
            sleep(self.sleep_time * 2)

        if count == self.retries:
            logging.critical('Reached the maximum connection attempts. Exiting...')
            run_flag = False
            self.close_udp_socket()
            exit(err_join)
        elif not run_flag:
            logging.debug('Received signal to exit. Exiting..')
            run_flag = False
            self.close_udp_socket()
            exit(err_user)

        count = 0
        joined_server = False
        while not joined_server and count < self.retries and run_flag:
            count += 1
            logging.debug('Tries: {0}'.format(count))

            joined_server = self.join_server()

            # Do nothing
            sleep(self.sleep_time * 2)

        # Exit in error if we failed connecting to the server
        if count == self.retries:
            logging.critical('Reached the maximum connection attempts. Exiting...')
            run_flag = False
            self.close_udp_socket()
            self.exit_server()
            exit(err_join)
        elif not run_flag:
            logging.debug('Received signal to exit. Exiting..')
            run_flag = False
            self.close_udp_socket()
            self.exit_server()
            exit(err_user)

        # Spawn listener and reader threads
        try:
            t_listener = Listener(0, 'listener-0', self.s_server_udp, self.q_listener)
            t_listener.daemon = True
            t_reader = Reader(1, 'reader-1', self.clients)
            t_reader.daemon = True

            t_listener.start()
            t_reader.start()

        # Loop until we are told to stop running
            while run_flag:
                # Read listener queue, and process message
                if not self.q_listener.empty():
                    msg_listener = self.q_listener.get(block=False)
                    logging.debug('Listener received: {0}'.format(msg_listener))

                    self.process_udp_messages(msg_listener)

                # Do nothing
                sleep(self.sleep_time)
        except KeyboardInterrupt:
            logging.warning('Received SIGINT signal. Exiting...')
            exit(err_exit)

        logging.debug('run_flag = {0}'.format(run_flag))

        # Stop reader thread, and wait for it to terminate
        # This doesn't work because the reader is waiting for user input. However, the reader should have exited itself
        # when it got the Ctrl+D, or it will be killed forcefully when the client exits.
        if t_reader.is_alive():
            logging.debug('Stopping reader thread...')
            t_reader.flag_run = False
            #t_reader.join()

        # Send stop message to server
        logging.debug('Exiting server...')
        self.exit_server()

        # Read listener queue for the exit message
        count = 0
        exited_server = False
        while not exited_server and count < self.retries:
            count += 1
            logging.debug('Tries: {0}'.format(count))

            if not self.q_listener.empty():
                msg_listener = self.q_listener.get(block=False)
                logging.debug('Listener received: {0}'.format(msg_listener))
                exited_server = self.exited_server(msg_listener)
                logging.debug('exited_server = {0}'.format(exited_server))
            else:
                logging.debug('Queue is empty')

            # Do nothing
            sleep(self.sleep_time)

        # Stop the listener thread and close UDP socket
        logging.debug('Stopping listener thread...')
        t_listener.flag_run = False
        t_listener.join()

        logging.debug('Closing UDP socket...')
        self.close_udp_socket()

        # Exit in error if we failed connecting to the server
        if count == self.retries:
            logging.critical('Reached the maximum attempts while exiting the server. Exiting...')
            exit(err_exit)

        exit(err_ok)

    def send_tcp_msg(self, conn, msg):
        """ Send message over TCP socket.

            :param  conn    Socket connection.
            :param  msg     Bytes object to send.
            :return Length in bytes of the message sent.
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

    def set_exit_handler(self, func):
        """ Signal handler set function.
        """
        # Save the original handlers
        self.original_sigint = signal.getsignal(signal.SIGINT)
        self.original_sigterm = signal.getsignal(signal.SIGTERM)

        # Start our own signal handlers
        signal.signal(signal.SIGTERM, func)
        signal.signal(signal.SIGINT, func)

    def stop(self, sig, func=None):
        """ Do required tasks to stop the client.
        """
        global run_flag

        # Restore the original signal handlers to allow to stop forcefully
        signal.signal(signal.SIGINT, self.original_sigint)
        signal.signal(signal.SIGTERM, self.original_sigterm)

        logging.warning('Signal %s received: Exiting gracefully (you can press [Ctrl]+[C] again to stop forcefully)...',
                        signals_to_names[sig])
        run_flag = False


class Listener (threading.Thread):
    """ Socket listener thread class.
    """

    def __init__(self, thread_id, name, udp_socket, msg_queue, sleep_time=0.2):
        """ Initialize instance variables.

            :param  thread_id   Thread's numeric ID.
            :param  name        Thread's name of the format "listener-<thread_id>".
            :param  udp_socket  UDP socket object to listen to.
            :param  msg_queue   Message queue to share the received messages.
            :param  sleep_time  Time to pause in between loops in sec.
        """
        threading.Thread.__init__(self)
        self.thread_id = thread_id  # Use socket port as the thread ID?
        self.name = name            # Of the format: listener-<thread_id>

        self.udp_socket = udp_socket    # UDP socket to listen to
        self.msg_queue = msg_queue      # Message queue to share the received messages.

        self.flag_run = True

        self.msg_leftovers_udp = bytes()    # If we receive the beginning of the next msg, save it here
        self.sleep_time = sleep_time        # Time to pause in between loops in sec

    def receive_udp_msg(self, conn):
        """ Receive message over UDP socket.

            :param  conn    UDP socket connection.
            :return Message received as a bytes object.
        """
        receiving = True

        # Check if last time we received data, we got the beginning of the next msg
        if self.msg_leftovers_udp != b'':
            msg = bytes(self.msg_leftovers_udp)
            self.msg_leftovers_udp = None       # Clear the buffer for the next time

            # Check if we already got a whole second message last time
            if b'\n' in msg:
                receiving = False

                b_tmp = msg.split(b'\n')
                msg = b_tmp[0] + b'\n'
                self.msg_leftovers_udp = b'\n'.join(b_tmp[1:])
        else:
            msg = bytes()

        while receiving and self.flag_run:
            ready = select.select([self.udp_socket], [], [], 0.5)[0]
            if ready:
                chunk = conn.recv(2048)

                if b'\n' in chunk:
                    receiving = False

                    b_tmp = chunk.split(b'\n')
                    chunk = b_tmp[0] + b'\n'
                    self.msg_leftovers_udp = b'\n'.join(b_tmp[1:])
                elif chunk == b'':
                    raise RuntimeError("Socket connection broken")

                msg += chunk
                logging.debug('chunk: {0}'.format(chunk))

        logging.debug('msg: {0}'.format(msg))
        logging.debug('msg_leftovers_udp: {0}'.format(self.msg_leftovers_udp))
        return msg

    def run(self):
        """ Run.
        """
        while self.flag_run:
            # Listen to UDP socket and put received messages in queue
            try:
                received = self.receive_udp_msg(self.udp_socket)
                self.msg_queue.put(received)
            except (OSError, InterruptedError, RuntimeError) as e1:
                logging.error('Failed receiving UDP message: {0}'.format(e1))
            except (KeyboardInterrupt, SystemExit):
                logging.warning('Received SIGINT signal. Exiting: {0}...'.format(self.name))
                return

            # Do nothing
            sleep(self.sleep_time)

        logging.debug('Received signal to exit from main thread. Exiting: {0}...'.format(self.name))


class Reader (threading.Thread):
    """ Console reader thread class.
    """

    def __init__(self, thread_id, name, clients, sender_timeout=1.0):
        """ Initialize instance variables.

            :param  thread_id       Thread's numeric ID.
            :param  name            Thread's name of the format "reader-<thread_id>".
            :param  clients         List of clients including this instance as per the Chatter.clients format.
            :param  sender_timeout  Timeout to wait for a message to be sent. Default is 1 sec.
        """
        threading.Thread.__init__(self)
        self.thread_id = thread_id
        self.name = name    # of the format: reader-<thread_id>

        self.flag_run = True    # Flag used by main thread to stop this thread
        self.run_flag = True    # Global flag used to tell Chatter to stop

        self.clients = clients  # List of clients including this instance with their screen names, IPs and UDP ports
        self.sender_timeout = sender_timeout    # Timeout to wait for a sender thread to return before going to the next

    def run(self):
        """ Run.
        """
        global run_flag

        while self.flag_run:
            # Read stdin input
            try:
                msg_input = input('{0}: '.format(self.clients[0]['screen_name']))
                logging.debug('msg_input = {0}'.format(msg_input))
            except EOFError:
                logging.warning('Ctrl+D input detected. Sending exit signal...')
                self.flag_run = False
                run_flag = False

                logging.debug('Received signal to exit from user. Exiting: {0}...'.format(self.name))
                return
            except (KeyboardInterrupt, SystemExit):
                logging.warning('Received SIGINT signal. Exiting: {0}...'.format(self.name))
                return

            # Send message to clients
            self.send_message(msg_input)

        logging.debug('Received signal to exit from main thread. Exiting: {0}...'.format(self.name))

    def send_message(self, msg):
        """ Spawn a Sender thread to send the message.

            :param  msg Message to send as a string.
        """
        # Spawn a sender thread for each client in the server, and save to list
        senders = list()
        for i, client in enumerate(self.clients):
            # Skip this client instance
            if i != 0:
                msg_processed = bytes(proto_udp_mesg.format(client['screen_name'], msg).encode(encoding='utf-8'))
                t_sender = Sender(i, 'sender-{0}'.format(client['screen_name']), client, msg_processed)
                t_sender.start()
                senders.append(t_sender)

        # Wait for the threads to finish
        while len(senders) != 0:
            for sender in senders:
                sender.join(timeout=self.sender_timeout)
                if not sender.is_alive():
                    senders.remove(sender)


class Sender (threading.Thread):
    """ Message sender thread class.
    """

    def __init__(self, thread_id, name, client, message):
        """ Initialize instance variables.

            :param  thread_id   Thread's numeric ID.
            :param  name        Thread's name of the format "sender-<thread_id>".
            :param  client      Client info to which to send the message.
            :param  message     Message to be sent as a bytes object.
        """
        threading.Thread.__init__(self)
        self.thread_id = thread_id  # Use socket port as the thread ID?
        self.name = name            # Of the format: sender-<thread_id>

        self.client = client
        self.s_client_udp = None    # UDP socket to talk to other clients
        self.msg = message

    def create_udp_socket(self):
        """ Create UDP socket ad connect to other client.
        """
        logging.info('Creating UDP socket to connect to {0}...'.format(self.client['screen_name']))

        # Create a UDP socket
        self.s_client_udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.s_client_udp.connect((self.client['ip'], self.client['udp_port']))

    def run(self):
        """ Run.
        """
        # Create socket
        try:
            self.create_udp_socket()
        except OSError as e1:
            logging.error('Could not create UDP socket to send message: {0}'.format(e1))
            return

        # Send message
        try:
            self.send_udp_msg(self.s_client_udp, self.msg)
        except (OSError, InterruptedError, RuntimeError) as e1:
            logging.error('Failed sending UDP message: {0}'.format(e1))
            return

    def send_udp_msg(self, conn, msg):
        """ Send message over UDP socket.

            :param  conn    Socket connection.
            :param  msg     Bytes object to send.
            :return Length in bytes of the message sent.
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
    chatter = Chatter(args.screen_name, args.server_hostname, args.server_port)
    #chatter.set_exit_handler(chatter.stop)     # Hndles the SIGINT  signal (Ctrl+C) to exit gracefully
    chatter.run()

    exit(err_ok)
