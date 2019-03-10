import socket
from threading import Thread
from collections import defaultdict
import re
from datetime import datetime as dt
from time import time, sleep
import os


class Client:
    """New class for client objects"""
    def __init__(self, name, conn, addr, room='common'):
        self.name = name
        self.conn = conn
        self.addr = addr
        self.room = room


class Server:
    """Describes server side of the chat"""
    def __init__(self, ip, port, max_conn_num):
        """
        Args:
            ip (str): ip address of the server
            port (int): port of the server
            max_conn_num (int): number of unaccepted connections before refusing a new one
        """
        self.ip = ip
        self.port = port
        self.max_conn_num = max_conn_num
        self.clients = []
        self.rooms = defaultdict(list)

    def remove_client(self, client_to_remove):
        """Close client connection and remove it from room and client list.
        Args:
            client_to_remove (Client): client object to remove
        """
        client_to_remove.conn.close()
        if client_to_remove in self.rooms[client_to_remove.room]:
            self.rooms[client_to_remove.room].remove(client_to_remove)

        if len(self.rooms[client_to_remove.room]) == 0:
            self.rooms.pop(client_to_remove.room)

        if client_to_remove in self.clients:
            self.clients.remove(client_to_remove)

    def broadcast(self, msg, room):
        """Send message to all clients of the room.
        Args:
            msg (byte): encoded string (e.g "example".encode())
            room (str): name of room
        """
        for client in self.clients:
            if client.room == room:
                try:
                    client.conn.send(msg)
                except:
                    self.remove_client(client)

    def show_online(self, client):
        """Show currently online clients in the room

        Args:
            client (Client): client which requested online list
            """
        online_string = "These users are currently online:\n"
        online_string += "\n".join([c.name for c in self.clients if c.room == client.room])
        client.conn.send(online_string.encode())

    def show_help(self, client):
        client.conn.send(
            ("--exit - leave chat\n" +
             "--online - show clients currently online\n" +
             "--rooms - show available rooms and number of users\n" +
             "--change_room 'new_room' - change to new room\n" +
             "--send_file 'file_path' - send file (centralized)\n" +
             "--get_file 'file_name' - download file from server (centralized)\n" +
             "--send_by_link 'file_path' - share file by link (decentralized)\n" +
             "--get_by_link 'file_link' - download file from client by link (decentralized)").encode())

    def show_rooms(self, client, top_n=3):
        """Show available rooms with the number of users
        Args:
            client (Client): client which requested rooms list

        """
        top_rooms = [r[0] for r in sorted(self.rooms.items(), key=lambda i: len(i[1]), reverse=True)][:top_n]
        res = '\n'.join(['{}: {} users'.format(r, len(self.rooms[r])) for r in top_rooms]) + '\n'
        client.conn.send(res.encode())

    def change_room(self, client, new_room):
        """Change room of the client"""
        old_room = client.room
        # delete client from old room
        if client in self.rooms[old_room]:
            self.rooms[old_room].remove(client)
        # delete old room if it is empty
        if len(self.rooms[old_room]) == 0:
            self.rooms.pop(old_room)

        self.broadcast('{} joined the room {}'.format(client.name, dt.now().strftime('%d-%m-%Y at %H:%M')).encode(),
                       new_room)

        # change client room in clients list
        for c in self.clients:
            if c == client:
                c.room = new_room

        self.broadcast('{} left the room {}'.format(client.name, dt.now().strftime('%d-%m-%Y at %H:%M')).encode(),
                       old_room)

        self.rooms[new_room].append(client)
        client.conn.send('Welcome to "{}" chat, {}!'.format(new_room, client.name).encode())

    def send_file(self, client, msg):
        """Receive file sent by client
        Args:
            client (Client): sender of the file
            msg (str): message from the sender (e.g. --get_file example.pdf)
        """
        cmd, file_path = msg.strip().split()
        client.conn.send('--ready_to_receive'.encode())
        with open('server_files/{}'.format(file_path), 'wb') as f:
            chunk = client.conn.recv(2048)
            while repr(chunk) != repr(b'--file_sent'):
                f.write(chunk)
                chunk = client.conn.recv(2048)
        self.broadcast("{} uploaded a file. Write '--get_file {}' to download it.".format(
            client.name, file_path).encode(), client.room)

    def get_file(self, client, msg):
        """Send file to client
        Args:
            client (Client): sender of the file
            msg (str): message from the sender (e.g. --get_file example.pdf)
        """
        cmd, file_path = msg.strip().split()

        try:
            with open("server_files/" + file_path, 'rb') as f:
                client.conn.send("--ready_to_send".encode())
                client.conn.sendfile(f, 0)
                print('{} has been successfully sent to client {} (ip: {})'.format(
                    file_path, client.name, client.addr[0]))
                # mark the end of file sending
                sleep(0.3)
                client.conn.send(b'--file_sent')
        except FileNotFoundError:
            print("There is no such file.")
            client.conn.send("There is no such file.".encode())

    def send_by_link(self, client, msg):
        """Decentralized way to share a file.
        Client will download file from client. Server only sends a link to the room.
        """
        file_name, ip, port = re.match('--send_by_link (.+)_(.+):(.+)', msg).groups()

        file_link = "{} shared file link. Type '--get_by_link {}_{}:{}'".format(
            client.name, file_name, ip, port)
        print(file_link)
        self.broadcast(file_link.encode(), client.room)

    def exit(self, client):
        """Process client command to exit and notify clients of the room"""
        self.remove_client(client)
        self.broadcast('{} left the room {}'.format(client.name, dt.now().strftime('%d-%m-%Y at %H:%M')).encode(),
                       client.room)

    def send_msg(self, sender, msg):
        msg_to_send = "{}: {}".format(sender.name, msg)

        print(msg_to_send)

        self.broadcast(msg_to_send.encode(), sender.room)

    @staticmethod
    def clear_files(ttl):
        """Delete files from server which older than ttl
        Args:
            ttl (int): time to live in minutes
        """
        ttl_minutes_ago = time() - 60 * ttl
        os.chdir('server_files')
        for f in os.listdir('.'):
            mtime = os.stat(f).st_mtime
            if mtime < ttl_minutes_ago:
                os.remove(f)
        os.chdir('..')

    def handle_client(self, client_conn, client_addr):
        """Handle client in a separate thread"""

        client_conn.send("Enter your name: ".encode())
        name = client_conn.recv(1024).decode().strip()

        client = Client(name, client_conn, client_addr)

        if len(self.rooms) != 0:
            client.conn.send("Available rooms:".encode())
            self.show_rooms(client)
        else:
            client.conn.send("There are currently no rooms. Be the first one to create!\n".encode())

        client.conn.send("Which room you want to join? (type new name to create room)".encode())
        room = client_conn.recv(1024).decode().strip()

        while not (re.match('[a-zA-Zа-яА-Я0-9-_*\s]{3,15}', room) and len(room) < 15):
            client_conn.send("Incorrect room name, try again:".encode())
            room = client_conn.recv(1024).decode().strip()

        client.room = room

        self.broadcast('{} joined {}'.format(client.name, dt.now().strftime('%d.%m.%Y at %H:%M')).encode(), client.room)

        self.clients.append(client)
        self.rooms[room].append(client)

        client.conn.send("Welcome to chat room '{}', {}!\n".format(client.room, client.name).encode())
        client.conn.send("Write '--help' to see available commands. If you want to leave - just type '--exit'".encode())

        while True:
            try:
                msg = client.conn.recv(2048).decode().strip()
                if msg:
                    if msg == '--exit':
                        self.exit(client)
                    elif msg == '--online':
                        self.show_online(client)
                    elif msg == '--help':
                        self.show_help(client)
                    elif '--rooms' in msg:
                        self.show_rooms(client)
                    elif '--change_room' in msg:
                        self.change_room(client, msg.split(' ')[1].strip())
                    elif re.match('--send_file (.+)', msg):
                        self.send_file(client, msg)
                    elif re.match('--get_file (.+)', msg):
                        self.get_file(client, msg)
                    elif re.match('--send_by_link (.+)', msg):
                        self.send_by_link(client, msg)
                    else:
                        self.send_msg(client, msg)
                else:
                    """message may have no content if the connection 
                    is broken, in this case we remove the connection"""
                    self.remove_client(client)
                    break
            except Exception as e:
                self.remove_client(client)
                break

    def start(self):
        print("Started server at {}:{}".format(self.ip, self.port))
        print("Listening...")
        # AF_INET - tcp socket, SOCK_STREAM - data is read in continuous flow, SOL_SOCKET - socket layer
        # SO_REUSEADDR flag tells the kernel to reuse a local socket in TIME_WAIT state, without waiting for
        # its natural timeout to expire. 1 is buffer
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # each 30 seconds while true loop will iterate
        server.settimeout(30)
        server.bind((self.ip, self.port))
        server.listen(self.max_conn_num)

        while True:
            Server.clear_files(ttl=1)
            try:
                conn, addr = server.accept()
                print(conn)

                Thread(target=self.handle_client, args=(conn, addr)).start()
            except socket.timeout:
                continue
            except:
                for client in self.clients:
                    self.remove_client(client)
                break
        server.close()


srvr = Server('127.0.0.1', 1702, 10)
srvr.start()
