"""Shared mandatory HTTP CONNECT proxy preflight; never fall back to direct."""
from __future__ import annotations

import base64
import http.client
import ipaddress
import os
import socket
import ssl
import sys
from urllib.parse import unquote, urljoin, urlsplit

DEFAULT_PROXY = "http://127.0.0.1:7890"
PROXY_KEYS = ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy")


class ProxyError(ValueError):
    pass


def select_proxy(explicit: str | None = None, env: dict[str, str] | None = None) -> str:
    env = os.environ if env is None else env
    if explicit is not None:
        return explicit.strip()
    return next((env[k].strip() for k in ("GEMINI_DELEGATE_PROXY", *PROXY_KEYS) if env.get(k, "").strip()), DEFAULT_PROXY)


def parse_proxy(raw: str):
    try:
        value = urlsplit(raw)
        if value.scheme != "http" or not value.hostname or not value.port or value.path not in ("", "/") or value.query or value.fragment:
            raise ValueError
        if any(c.isspace() for c in raw):
            raise ValueError
        return value
    except ValueError:
        raise ProxyError("拒绝启动：代理必须是带有效端口的 http://host:port URL（支持本地 mixed port；不支持 SOCKS）。") from None


def proxy_environment(raw: str, env: dict[str, str] | None = None) -> dict[str, str]:
    parse_proxy(raw)
    child = dict(os.environ if env is None else env)
    for key in PROXY_KEYS:
        child[key] = raw
    child["NO_PROXY"] = child["no_proxy"] = ""
    return child


def fetch_https(raw: str, url: str, *, max_bytes: int, timeout: int = 10) -> bytes:
    """Fetch HTTPS via explicit CONNECT; validate every redirect and limit size."""
    value = parse_proxy(raw)
    headers = {}
    if value.username is not None:
        auth = f"{unquote(value.username)}:{unquote(value.password or '')}".encode()
        headers["Proxy-Authorization"] = "Basic " + base64.b64encode(auth).decode("ascii")
    for _ in range(5):
        target = urlsplit(url)
        if target.scheme != "https" or not target.hostname or target.username or target.password:
            raise ProxyError("代理请求目标及重定向必须是无凭据的 HTTPS URL。")
        conn = http.client.HTTPSConnection(value.hostname, value.port, timeout=timeout, context=ssl.create_default_context())
        try:
            conn.set_tunnel(target.hostname, target.port or 443, headers=headers)
            path = target.path or "/"
            if target.query:
                path += "?" + target.query
            conn.request("GET", path, headers={"User-Agent": "gemini-delegate/1.5.3"})
            response = conn.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader("Location")
                if not location:
                    raise ProxyError("代理请求重定向缺少 Location。")
                url = urljoin(url, location)
                continue
            if response.status != 200:
                raise ProxyError(f"代理请求 HTTP {response.status}；不会尝试直连。")
            length = response.getheader("Content-Length")
            if length and int(length) > max_bytes:
                raise ProxyError("代理请求响应超过大小限制。")
            body = response.read(max_bytes + 1)
            if len(body) > max_bytes:
                raise ProxyError("代理请求响应超过大小限制。")
            return body
        except ProxyError:
            raise
        except (OSError, http.client.HTTPException, ValueError):
            raise ProxyError("代理 CONNECT/TLS/响应失败；不会尝试直连。") from None
        finally:
            conn.close()
    raise ProxyError("代理请求重定向次数超过限制。")


def probe_egress(raw: str) -> dict[str, str]:
    try:
        body = fetch_https(raw, "https://www.cloudflare.com/cdn-cgi/trace", max_bytes=16384).decode("utf-8", "replace")
        fields = dict(line.split("=", 1) for line in body.splitlines() if "=" in line)
        address = ipaddress.ip_address(fields.get("ip", ""))
        if not address.is_global or not fields.get("loc") or not fields.get("colo"):
            raise ValueError("invalid trace")
        return {k: fields[k] for k in ("ip", "loc", "colo")}
    except ProxyError:
        raise
    except ValueError:
        raise ProxyError("拒绝启动：代理出口预检失败（CONNECT/TLS/trace）。检查代理后再运行；不会尝试直连。") from None


def prepare_proxy(explicit: str | None = None, env: dict[str, str] | None = None) -> tuple[dict[str, str], dict[str, str]]:
    raw = select_proxy(explicit, env)
    child = proxy_environment(raw, env)
    value = parse_proxy(raw)
    try:
        with socket.create_connection((value.hostname, value.port), timeout=3):
            pass
    except OSError:
        raise ProxyError(f"拒绝启动：代理 {value.hostname}:{value.port} 不可达；不会尝试直连。") from None
    fields = probe_egress(raw)
    print(f"proxy: {value.hostname}:{value.port}; egress ip={fields['ip']} colo={fields['colo']} loc={fields['loc']}; NO_PROXY cleared", file=sys.stderr)
    return child, fields
