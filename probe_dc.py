import asyncio
import socket

from python_socks import ProxyType
from python_socks.async_.asyncio import Proxy

IPS = ["149.154.175.100", "149.154.167.51", "149.154.167.91",
       "91.108.56.130", "91.108.4.76"]


def parse_proxy():
    for line in open("paid_proxies.txt", encoding="utf-8"):
        line = line.strip()
        if not line.startswith("socks5://"):
            continue
        cred, hp = line.split("://", 1)[1].split("@")
        user, pwd = cred.split(":")
        host, port = hp.split(":")
        return user, pwd, host, int(port)
    return None


async def main():
    user, pwd, host, port = parse_proxy()
    for ip in IPS:
        try:
            s = socket.create_connection((ip, 443), timeout=8)
            s.close()
            print("DIRECT", ip, "OK", flush=True)
        except Exception as e:
            print("DIRECT", ip, type(e).__name__, flush=True)
        try:
            pr = Proxy.create(proxy_type=ProxyType.SOCKS5, host=host,
                              port=port, username=user, password=pwd,
                              rdns=True)
            s = await asyncio.wait_for(pr.connect(ip, 443), 10)
            s.close()
            print("PROXY", ip, "OK", flush=True)
        except Exception as e:
            print("PROXY", ip, type(e).__name__, str(e)[:60], flush=True)


asyncio.run(main())
