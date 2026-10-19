"""Adapted from heartbeat2/tests/e2e/loopback.py at HB2 commit 3ed7a21."""
import ipaddress
import socket


def install(setattr_fn=setattr, allowed_hosts=()):
    connect, connect_ex = socket.socket.connect, socket.socket.connect_ex
    sendto, getaddrinfo = socket.socket.sendto, socket.getaddrinfo
    backend_ips = set()

    def check(address, family=None):
        if family == socket.AF_UNIX:
            return
        host = address[0] if isinstance(address, tuple) else address
        try:
            allowed = host == "localhost" or ipaddress.ip_address(host).is_loopback or host in backend_ips
        except (ValueError, TypeError):
            allowed = False
        if not allowed:
            raise PermissionError("E2E network boundary: non-loopback address refused")

    def guarded_connect(sock, address):
        check(address, sock.family)
        return connect(sock, address)

    def guarded_connect_ex(sock, address):
        check(address, sock.family)
        return connect_ex(sock, address)

    def guarded_sendto(sock, data, *args):
        check(args[-1], sock.family)
        return sendto(sock, data, *args)

    def guarded_getaddrinfo(host, *args, **kwargs):
        if host in allowed_hosts:
            rows = getaddrinfo(host, *args, **kwargs)
            backend_ips.update(row[4][0] for row in rows)
            return rows
        check(host)
        return getaddrinfo(host, *args, **kwargs)

    for name, fn in (("connect", guarded_connect), ("connect_ex", guarded_connect_ex), ("sendto", guarded_sendto)):
        setattr_fn(socket.socket, name, fn)
    setattr_fn(socket, "getaddrinfo", guarded_getaddrinfo)
