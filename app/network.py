"""Public-network-only connections, installed inside the isolated media worker."""
import ipaddress
import socket
import urllib.request
from urllib.parse import urlsplit


def validate_url(url):
    try:
        parts = urlsplit(url)
        if (parts.scheme not in ('http', 'https') or not parts.hostname
                or parts.username is not None or parts.password is not None
                or parts.port not in (None, 80 if parts.scheme == 'http' else 443)):
            raise ValueError('不允许的媒体地址')
    except (TypeError, ValueError) as error:
        raise ValueError('不允许的媒体地址') from error
    return parts


def _check_addresses(addresses):
    if not addresses:
        raise ValueError('域名没有可用地址')
    for _, _, _, _, address in addresses:
        ip = ipaddress.ip_address(address[0].split('%')[0])
        if (not ip.is_global or ip.is_multicast
                or (ip.version == 6 and (ip.ipv4_mapped or ip.sixtofour or ip.teredo))):
            raise ValueError('拒绝访问本机、内网或保留网络地址')
    return addresses


def public_addresses(host, port):
    return _check_addresses(socket.getaddrinfo(host, port, type=socket.SOCK_STREAM))


def install_socket_guard():
    """Pin checked DNS answers at connect time; never install in the API process."""
    resolve = socket.getaddrinfo
    connect = socket.socket.connect
    connect_ex = socket.socket.connect_ex

    def checked_dns(*args, **kwargs):
        return _check_addresses(resolve(*args, **kwargs))

    def pinned(sock, address, method):
        if sock.family not in (socket.AF_INET, socket.AF_INET6):
            raise ValueError('媒体进程不允许访问本机套接字')
        if address[1] not in (80, 443):
            raise ValueError('媒体进程只允许 HTTP/HTTPS 端口')
        answers = _check_addresses(resolve(address[0], address[1], sock.family, socket.SOCK_STREAM))
        return method(sock, answers[0][4])

    socket.getaddrinfo = checked_dns
    socket.socket.connect = lambda sock, address: pinned(sock, address, connect)
    socket.socket.connect_ex = lambda sock, address: pinned(sock, address, connect_ex)


class PublicRedirect(urllib.request.HTTPRedirectHandler):
    max_redirections = 5
    max_repeats = 1

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def open_public(url, timeout=30, headers=None):
    """Called only after install_socket_guard, including on every redirect."""
    target = url.full_url if isinstance(url, urllib.request.Request) else url
    validate_url(target)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), PublicRedirect())
    request = url if isinstance(url, urllib.request.Request) else urllib.request.Request(url, headers=headers or {})
    return opener.open(request, timeout=timeout)
