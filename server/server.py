#!/usr/bin/env python3
"""
zgrok - Servidor de Túnel Reverso Pessoal
Gerencia conexões WebSocket de clientes locais e encaminha requisições HTTP externas.
"""

import asyncio
import base64
import json
import logging
import os
import secrets
import string
import time
import uuid
from typing import Dict, Optional
from aiohttp import web, WSMsgType

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("zgrok-server")

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")
DEFAULT_CONFIG = {
    "host": "0.0.0.0",
    "port": 8080,
    "auth_token": "",  # Deixe vazio para desativar ou defina um token secreto
    "public_url_prefix": "https://meudominio.com/zgrok",
    "request_timeout": 30,
    "id_length": 6
}

def load_config() -> dict:
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                return {**DEFAULT_CONFIG, **cfg}
        except Exception as e:
            logger.warning(f"Erro ao ler config.json ({e}). Usando configurações padrão.")
    return DEFAULT_CONFIG.copy()

config = load_config()

# Gerenciamento de túneis
# tunnel_id -> {'ws': WebSocketResponse, 'created_at': float, 'remote': str}
active_tunnels: Dict[str, dict] = {}

# request_id -> asyncio.Future
pending_responses: Dict[str, asyncio.Future] = {}

def generate_tunnel_id(length: int = 6) -> str:
    alphabet = string.ascii_lowercase + string.digits
    while True:
        tid = "".join(secrets.choice(alphabet) for _ in range(length))
        if tid not in active_tunnels:
            return tid

async def ws_tunnel_handler(request: web.Request) -> web.WebSocketResponse:
    """Endpoint WebSocket onde o cliente local conecta para registrar o túnel."""
    ws = web.WebSocketResponse(heartbeat=15.0, max_msg_size=10 * 1024 * 1024)
    await ws.prepare(request)

    # Validar token de autenticação se configurado no servidor
    expected_token = config.get("auth_token", "").strip()
    client_token = request.query.get("token", "").strip()
    if expected_token and client_token != expected_token:
        logger.warning("Conexão WebSocket rejeitada: token inválido")
        await ws.send_json({"type": "error", "message": "Token de autenticação inválido"})
        await ws.close()
        return ws

    # ID automático (ou customizado opcional)
    requested_id = request.query.get("id", "").strip().lower()
    if requested_id and requested_id not in active_tunnels:
        tunnel_id = requested_id
    else:
        tunnel_id = generate_tunnel_id(config.get("id_length", 6))

    active_tunnels[tunnel_id] = {
        "ws": ws,
        "created_at": time.time(),
        "remote": request.remote
    }

    public_base = config.get("public_url_prefix", "").rstrip("/")
    if not public_base:
        scheme = request.scheme
        host = request.host
        public_base = f"{scheme}://{host}/zgrok"

    public_url = f"{public_base}/{tunnel_id}/"

    logger.info(f"[+] Novo túnel registrado: {tunnel_id} ({request.remote}) -> {public_url}")

    # Notificar cliente local com o tunnel_id e a URL pública
    await ws.send_json({
        "type": "init_ok",
        "tunnel_id": tunnel_id,
        "public_url": public_url
    })

    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                try:
                    payload = json.loads(msg.data)
                    msg_type = payload.get("type")

                    if msg_type == "response":
                        req_id = payload.get("request_id")
                        if req_id and req_id in pending_responses:
                            future = pending_responses.pop(req_id)
                            if not future.done():
                                future.set_result(payload)
                    elif msg_type == "ping":
                        await ws.send_json({"type": "pong"})
                except json.JSONDecodeError:
                    logger.warning("Mensagem JSON inválida recebida do cliente WebSocket")
            elif msg.type == WSMsgType.ERROR:
                logger.error(f"Erro no WebSocket do túnel {tunnel_id}: {ws.exception()}")
                break
    finally:
        if tunnel_id in active_tunnels:
            del active_tunnels[tunnel_id]
            logger.info(f"[-] Túnel desconectado: {tunnel_id}")

    return ws

async def http_proxy_handler(request: web.Request) -> web.Response:
    """Recebe requisições HTTP externas do Apache e repassa para o túnel correspondente."""
    tunnel_id = request.match_info.get("tunnel_id", "").lower()
    subpath = request.match_info.get("subpath", "")
    
    if not subpath.startswith("/"):
        subpath = "/" + subpath

    if request.query_string:
        full_path = f"{subpath}?{request.query_string}"
    else:
        full_path = subpath

    tunnel = active_tunnels.get(tunnel_id)
    if not tunnel:
        return web.Response(
            status=404,
            content_type="text/html",
            text=f"""<!DOCTYPE html>
<html>
<head><title>zgrok - Túnel Não Encontrado</title><meta charset="utf-8"></head>
<body style="font-family:sans-serif;text-align:center;padding:50px;background:#0f172a;color:#e2e8f0;">
    <h1 style="color:#ef4444;">404 - Túnel Não Encontrado</h1>
    <p>O túnel <code>{tunnel_id}</code> não está conectado ou expirou.</p>
    <p style="color:#94a3b8;font-size:14px;">zgrok reverse tunnel server</p>
</body>
</html>"""
        )

    ws: web.WebSocketResponse = tunnel["ws"]
    if ws.closed:
        return web.Response(
            status=502,
            content_type="text/plain",
            text="502 Bad Gateway: O cliente local desconectou."
        )

    raw_body = await request.read()
    body_b64 = base64.b64encode(raw_body).decode("utf-8") if raw_body else ""

    request_id = str(uuid.uuid4())

    forward_headers = {}
    for h_name, h_val in request.headers.items():
        if h_name.lower() not in ("host", "connection", "upgrade", "content-length"):
            forward_headers[h_name] = h_val

    forward_headers["X-Forwarded-For"] = request.remote or ""
    forward_headers["X-Forwarded-Proto"] = request.scheme
    forward_headers["X-Zgrok-Tunnel"] = tunnel_id

    req_payload = {
        "type": "request",
        "request_id": request_id,
        "method": request.method,
        "path": full_path,
        "headers": forward_headers,
        "body_b64": body_b64
    }

    loop = asyncio.get_running_loop()
    future = loop.create_future()
    pending_responses[request_id] = future

    try:
        await ws.send_json(req_payload)
        timeout = config.get("request_timeout", 30)
        res_payload = await asyncio.wait_for(future, timeout=timeout)
    except asyncio.TimeoutError:
        pending_responses.pop(request_id, None)
        return web.Response(status=504, text="504 Gateway Timeout: O servidor local demorou a responder.")
    except Exception as e:
        pending_responses.pop(request_id, None)
        logger.error(f"Erro ao encaminhar requisição para {tunnel_id}: {e}")
        return web.Response(status=502, text=f"502 Bad Gateway: {e}")

    status_code = res_payload.get("status", 200)
    res_headers = res_payload.get("headers", {})
    res_body_b64 = res_payload.get("body_b64", "")

    if res_body_b64:
        try:
            body_bytes = base64.b64decode(res_body_b64)
        except Exception:
            body_bytes = b""
    else:
        body_bytes = b""

    filtered_headers = {}
    for h, v in res_headers.items():
        h_lower = h.lower()
        if h_lower not in ("content-length", "connection", "transfer-encoding", "content-encoding"):
            # Ajustar redirecionamento Location para permanecer no túnel
            if h_lower == "location" and v.startswith("/"):
                filtered_headers[h] = f"/zgrok/{tunnel_id}{v}"
            else:
                filtered_headers[h] = v

    # Injetar cookie para que requisições subsequentes do navegador identifiquem o túnel
    response = web.Response(
        status=status_code,
        headers=filtered_headers,
        body=body_bytes
    )
    response.set_cookie(
        name="zgrok_tunnel",
        value=tunnel_id,
        path="/",
        samesite="Lax"
    )
    return response

async def status_handler(request: web.Request) -> web.Response:
    """Retorna o status geral do servidor zgrok."""
    return web.json_response({
        "status": "online",
        "service": "zgrok",
        "active_tunnels": len(active_tunnels),
        "uptime": time.time()
    })

def create_app() -> web.Application:
    app = web.Application()
    # Conexão WebSocket para o cliente local
    app.router.add_get("/zgrok-ws", ws_tunnel_handler)
    # Rota de status do servidor
    app.router.add_get("/zgrok-status", status_handler)
    # Rota pública de roteamento por path
    app.router.add_route("*", "/zgrok/{tunnel_id}", http_proxy_handler)
    app.router.add_route("*", "/zgrok/{tunnel_id}/{subpath:.*}", http_proxy_handler)
    return app

if __name__ == "__main__":
    app = create_app()
    host = config.get("host", "0.0.0.0")
    port = int(config.get("port", 8080))
    logger.info(f"Iniciando zgrok-server em http://{host}:{port}")
    web.run_app(app, host=host, port=port)
