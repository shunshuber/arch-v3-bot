"""Local SOCKS5 relay with no auth that terminates auth to an upstream proxy.

Chromium cannot authenticate SOCKS5 proxies. This tiny relay accepts plain
SOCKS5 on localhost and opens each connection through the authenticated
upstream (python_socks), which makes paid SOCKS proxies usable by Playwright.

Env:
  DSA_PROXY_URL   upstream socks5://user:pass@host:port
  DSA_RELAY_PORT  local port (default 1080)

Run: python socks_relay.py
"""
import asyncio
import os
import socket

from python_socks.async_.asyncio import Proxy

UPSTREAM = os.getenv("DSA_PROXY_URL", "").strip()
PORT = int(os.getenv("DSA_RELAY_PORT", "1080"))
_loop = None


async def _sendall(sock, data):
    view = memoryview(data)
    while view:
        sent = await _loop.sock_send(sock, view)
        if not sent:
            raise ConnectionError("send returned 0")
        view = view[sent:]


async def _pipe(src, dst):
    try:
        while True:
            chunk = await _loop.sock_recv(src, 65536)
            if not chunk:
                break
            await _sendall(dst, chunk)
    except (ConnectionError, OSError, asyncio.CancelledError):
        pass
    finally:
        for s in (src, dst):
            try:
                s.close()
            except Exception:
                pass


async def _handle(client, _addr):
    try:
        greeting = await _loop.sock_recv(client, 262)
        if not greeting or greeting[0] != 5:
            return
        await _sendall(client, b"\x05\x00")
        req = await _loop.sock_recv(client, 262)
        if len(req) < 5 or req[0] != 5 or req[1] != 1:
            return
        atyp = req[3]
        if atyp == 1:
            host = socket.inet_ntoa(req[4:8])
            port = int.from_bytes(req[8:10], "big")
        elif atyp == 3:
            length = req[4]
            host = req[5:5 + length].decode("utf-8", "replace")
            port = int.from_bytes(req[5 + length:7 + length], "big")
        else:
            return
        proxy = Proxy.from_url(UPSTREAM)
        upstream = await proxy.connect(dest_host=host, dest_port=port, timeout=25)
        upstream.setblocking(False)
        await _sendall(
            client, b"\x05\x00\x00\x01\x7f\x00\x00\x01" + port.to_bytes(2, "big"))
        await asyncio.gather(_pipe(client, upstream), _pipe(upstream, client))
    except Exception:
        try:
            client.close()
        except Exception:
            pass


async def main():
    global _loop
    _loop = asyncio.get_running_loop()
    if not UPSTREAM:
        raise SystemExit("DSA_PROXY_URL is empty")
    server = await asyncio.start_server(_handle, "127.0.0.1", PORT)
    print(f"relay ready 127.0.0.1:{PORT} -> {UPSTREAM.split('@')[-1]}",
          flush=True)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
