import socket
import select
import sys
import os
from time import time, sleep
from threading import Thread
import re
import errno


class ClientApp:
    """Client side of the chat"""

    def __init__(self, server_addr):
        self.server = None
        self.server_addr = server_addr

    @property
    def server_addr(self):
        """Property which helps validate server address and create connection with server"""
        return self._server_addr

    @server_addr.setter
    def server_addr(self, value):

        if len(value) == 2 and re.match('\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}', value[0]):
            try:
                self._server_addr = value
                self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.server.connect((value[0], int(value[1])))
            except Exception as e:
                print("Cannot connect to the server")
                raise e
        else:
            raise Exception("Incorrect server address (ip: string, port: int)")

    def send_file_p2p(self, client_conn, client_addr, file_path):
        """Send file in a decentralized way. Client to client
        Args:
            client_conn: client connection where to send file
            client_addr: adrress of the client where to send
            file_path: path of the file to send
        """
        try:
            with open(file_path, 'rb') as f:
                client_conn.sendfile(f, 0)
                print('{} has been successfully sent to ip: {}'.format(
                    file_path, client_addr[0]))
            # mark the end of file sending
            sleep(0.3)
            client_conn.send(b'--file_sent')
        except FileNotFoundError:
            print("There is no such file.")

    def open_link_server(self, file_path):
        """Open port via which file can be downloaded by another client. Link will be available only for a minute."""
        file_link = socket.socket()
        file_link.settimeout(15)
        # port 0 means "any" free port
        file_link.bind(("127.0.0.1", 0))
        ip, port = file_link.getsockname()
        file_link.listen(3)
        self.server.send('--send_by_link {}_{}:{}'.format(file_path, ip, port).encode())
        shut_time = time() + 60 * 1

        while time() < shut_time:
            try:
                client, addr = file_link.accept()
                Thread(target=self.send_file_p2p, args=(client, addr, file_path)).start()
            except socket.timeout:
                continue

    def send_by_link(self, message):
        cmd, file_path = message.strip().split()
        if os.path.isfile(file_path):
            Thread(target=self.open_link_server, args=(file_path,)).start()
        else:
            print("There is no such file.")

    def get_by_link(self, ip, port, file_name):
        """Download file from another client (decentralized way)"""
        try:
            seeder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            seeder.connect((ip, int(port)))

            with open('dist-{}'.format(file_name), 'wb') as f:
                chunk = seeder.recv(2048)
                while repr(chunk) != repr(b'--file_sent'):
                    f.write(chunk)
                    chunk = seeder.recv(2048)
            print('File has been successfully downloaded!')
        except socket.error as serr:
            if serr.errno == errno.ECONNREFUSED:
                print('Link expired')

    def send_file(self, message):
        """Send file to the server (centralized way)"""
        cmd, file_path = message.strip().split()

        try:
            with open(file_path, 'rb') as f:
                # send a command to the server that now we will send a file
                self.server.send(message.encode())
                if self.server.recv(2048).decode() == '--ready_to_receive':
                    self.server.sendfile(f, 0)
                    print('File has been successfully sent.')
            # mark the end of file sending
            sleep(0.3)
            self.server.send(b'--file_sent')
        except FileNotFoundError:
            print("There is no such file.")

    def get_file(self, message):
        """Get file from the server (centralized way)"""
        cmd, file_path = message.strip().split()
        # send a command to the server that now we will download a file
        self.server.send(message.encode())
        if self.server.recv(2048).decode() == '--ready_to_send':
            with open('downloads/{}'.format(file_path), 'wb') as f:
                chunk = self.server.recv(2048)
                while repr(chunk) != repr(b'--file_sent'):
                    f.write(chunk)
                    chunk = self.server.recv(2048)
            print("File has been successfully downloaded!")
        else:
            print("There is no such file.")

    def start(self):
        while True:

            try:

                # maintains a list of possible input streams
                sockets_list = [sys.stdin, self.server]
                """ There are two possible input situations. Either the
                user wants to give  manual input to send to other people,
                or the server is sending a message  to be printed on the
                screen. Select returns from sockets_list, the stream that
                is reader for input. So for example, if the server wants
                to send a message, then the if condition will hold true
                below.If the user wants to send a message, the else
                condition will evaluate as true"""
                read_sockets, write_socket, error_socket = select.select(sockets_list, [], [])

                message = None

                for sckt in read_sockets:
                    if sckt == self.server:
                        message = sckt.recv(2048).decode()
                        print(message)
                    else:
                        message = sys.stdin.readline()
                        # in case client just presses enter
                        if message == '\n':
                            pass
                        elif '--exit' in message:
                            self.server.send(message.encode())
                            os._exit(0)
                        elif re.match('--send_file (.+)', message):  # '--send_file' in message:
                            self.send_file(message)
                        elif re.match('--get_file (.+)', message):  # '--get_file' in message:
                            self.get_file(message)
                        elif re.match('--send_by_link (.+)', message):  # '--send_by_link' in message:
                            self.send_by_link(message)
                        elif '--get_by_link' in message:
                            try:
                                file_name, ip, port = re.match('--get_by_link (.+)_(.+):(.+)', message).groups()
                                Thread(target=self.get_by_link, args=(ip, port, file_name)).start()
                            except Exception as e:
                                print("Something went wrong...\n")
                                print(str(e))
                        else:
                            self.server.send(message.encode())
                            sys.stdout.flush()
                # if connection with server is lost, break inf loop
                if message == '':
                    break
            except Exception as e:
                print(str(e))
                self.server.send('--exit'.encode())


app = ClientApp(('127.0.0.1', 1702))
app.start()
