yachat
======

Chatroom server-client application. It consists of 2 modules:

* **server**: Membership chatroom server.

* **client**: Chatter chat client.


Chatter: Chat Client
--------------------

### Requirements

* Python 3.6 or higher.


### Usage

```
usage: client.py [-h] [-f LOG_FILE] [-l LOG_LEVEL]
                 screen_name server_hostname server_port

YaChat Chatter client.

positional arguments:
  screen_name           Screen name of chat user.
  server_hostname       Hostname of chat server.
  server_port           Port of chat server.

optional arguments:
  -h, --help            show this help message and exit
  -f LOG_FILE, --log-file LOG_FILE
                        Log file path. Log will print to stdin by default.
  -l LOG_LEVEL, --log-level LOG_LEVEL
                        Verbosity level of the logger. Uses ERROR by default.
```


Server: Chat Membership Server
------------------------------

WIP
