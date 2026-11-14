"""Controlled socket-return suspension, not a performance benchmark."""

import socket
import sys
import threading

from dexpot import Dex

port = int(sys.argv[1])
mode = sys.argv[2]
release = threading.Event()
owners = set()
stalled = False
count = 0
write_rpcs = 0
try:
    from dexpot._gil_io import SocketIO
except ImportError:
    write_rpcs = -1
else:
    original_call = SocketIO.call

    def counted_call(self, conn, operation, argument, timeout):
        global write_rpcs
        if operation == "sendall":
            write_rpcs += 1
        return original_call(self, conn, operation, argument, timeout)

    SocketIO.call = counted_call


def control():
    sys.stdin.buffer.read(1)
    release.set()


threading.Thread(target=control, daemon=True).start()
original_sendall = socket.socket.sendall
original_recv = socket.socket.recv


def owned(conn):
    return threading.get_ident() in owners and conn.getsockname()[1] == port


def sendall(conn, data, *args, **kwargs):
    global stalled
    result = original_sendall(conn, data, *args, **kwargs)
    if mode == "send" and owned(conn) and not stalled:
        stalled = True
        print("CONTROLLED_POST_SEND_STALL", flush=True)
        release.wait(5)
    return result


def recv(conn, *args, **kwargs):
    global stalled
    data = original_recv(conn, *args, **kwargs)
    if mode == "recv" and data and owned(conn) and not stalled:
        stalled = True
        print("CONTROLLED_POST_RECV_STALL", flush=True)
        release.wait(5)
    return data


socket.socket.sendall = sendall
socket.socket.recv = recv
app = Dex()


@app.get("/")
def root() -> dict:
    global count
    count += 1
    owners.add(threading.get_ident())
    return {"count": count, "handler_thread": threading.get_ident(), "write_rpcs": write_rpcs}


app.serve(host="127.0.0.1", port=port)
