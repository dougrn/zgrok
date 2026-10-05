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
    
    # Suporte a tunnel_id fixo para proxy catch-all
    fixed_id = config.get("fixed_tunnel_id", "").strip()
    if fixed_id:
        tunnel_id = fixed_id
    elif requested_id and requested_id not in active_tunnels:
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

    # Suporte a múltiplos túneis simultâneos com ID
    if config.get("wildcard_subdomain", False):
        base_clean = public_base.replace("https://", "").replace("http://", "").split("/")[0]
        proto = "https" if public_base.startswith("https") else "http"
        public_url = f"{proto}://{tunnel_id}.{base_clean}/"
    elif public_base.endswith("/zgrok"):
        public_url = f"{public_base}/{tunnel_id}/"
    else:
        # Link exclusivo com o ID do túnel sem /zgrok (ex: https://zgrok.meudominio.com/frontend/)
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

async def forward_to_tunnel(tunnel_id: str, subpath: str, request: web.Request) -> web.Response:
    """Encaminha uma requisição HTTP para o cliente WebSocket correspondente."""
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
            if h_lower == "location" and v.startswith("/") and not (config.get("subdomain_mode", False) or not config.get("public_url_prefix", "").rstrip("/").endswith("/zgrok")):
                filtered_headers[h] = f"/zgrok/{tunnel_id}{v}"
            else:
                filtered_headers[h] = v

    response = web.Response(
        status=status_code,
        headers=filtered_headers,
        body=body_bytes
    )
    response.set_cookie(
        name="zgrok_tunnel",
        value=tunnel_id,
        path="/",
        samesite="Lax",
        max_age=86400 * 30
    )
    return response

def format_uptime(seconds: float) -> str:
    """Formata o tempo de conexão do túnel em formato legível."""
    sec = max(0, int(seconds))
    if sec < 60:
        return f"{sec}s"
    elif sec < 3600:
        return f"{sec // 60}m {sec % 60}s"
    else:
        return f"{sec // 3600}h {(sec % 3600) // 60}m"

def render_tunnel_not_found(tunnel_id: str) -> web.Response:
    """Retorna página 404 quando o túnel requisitado não existe."""
    return web.Response(
        status=404,
        content_type="text/html",
        text=f"""<!DOCTYPE html>
<html lang="pt-BR">
<head><title>zgrok - Túnel Não Encontrado</title><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,sans-serif;text-align:center;padding:50px 20px;background:#0f172a;color:#e2e8f0;">
    <h1 style="color:#ef4444;margin-bottom:12px;">404 - Túnel Não Encontrado</h1>
    <p style="color:#94a3b8;font-size:16px;">O túnel <code style="background:#1e293b;padding:3px 8px;border-radius:6px;color:#f8fafc;">{tunnel_id}</code> não está conectado ou expirou.</p>
    <p style="margin-top:25px;"><a href="/switch" style="color:#38bdf8;text-decoration:none;font-weight:600;">&larr; Ver túneis ativos</a></p>
    <p style="color:#64748b;font-size:13px;margin-top:40px;">zgrok reverse tunnel server</p>
</body>
</html>"""
    )

def render_tunnel_selector(request: web.Request) -> web.Response:
    """Renderiza tela visual moderna para seleção de túnel quando múltiplos estão ativos."""
    current_cookie = request.cookies.get("zgrok_tunnel", "").strip().lower()
    
    cards_html = []
    for tid, info in active_tunnels.items():
        is_active_cookie = (tid == current_cookie)
        active_badge = '<span style="background:#059669;color:#fff;padding:2px 8px;border-radius:12px;font-size:11px;font-weight:bold;margin-left:8px;">SELECIONADO</span>' if is_active_cookie else ''
        uptime_str = format_uptime(time.time() - info.get("created_at", time.time()))
        remote_ip = info.get("remote", "desconhecido")
        
        cards_html.append(f"""
        <div style="background:#1e293b;border:1px solid #334155;border-radius:12px;padding:20px;margin-bottom:16px;display:flex;align-items:center;justify-content:space-between;gap:15px;flex-wrap:wrap;">
            <div>
                <div style="display:flex;align-items:center;margin-bottom:6px;">
                    <span style="font-size:20px;font-weight:700;color:#f8fafc;font-family:monospace;">{tid}</span>
                    {active_badge}
                </div>
                <div style="color:#94a3b8;font-size:13px;">
                    <span>Origem: <code style="color:#cbd5e1;">{remote_ip}</code></span> • <span>Uptime: {uptime_str}</span>
                </div>
            </div>
            <div>
                <a href="/switch?to={tid}" style="display:inline-block;background:#38bdf8;color:#0f172a;font-weight:700;font-size:14px;padding:10px 20px;border-radius:8px;text-decoration:none;">
                    Entrar no Túnel &rarr;
                </a>
            </div>
        </div>
        """)
    
    cards_joined = "".join(cards_html)
    
    html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>zgrok - Selecione o Túnel</title>
</head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,sans-serif;max-width:650px;margin:50px auto;padding:20px;background:#0f172a;color:#e2e8f0;line-height:1.5;">
    <div style="text-align:center;margin-bottom:30px;">
        <h1 style="color:#38bdf8;font-size:26px;margin:0 0 8px 0;">
            ⚡ zgrok
        </h1>
        <p style="color:#94a3b8;font-size:15px;margin:0;">
            Múltiplos túneis estão ativos no momento ({len(active_tunnels)}). Selecione qual projeto deseja acessar neste navegador:
        </p>
    </div>

    <div>
        {cards_joined}
    </div>

    <div style="text-align:center;margin-top:30px;padding-top:20px;border-top:1px solid #1e293b;color:#64748b;font-size:13px;">
        <p style="margin:4px 0;">💡 Você pode alternar de projeto a qualquer momento acessando <code>/switch</code>.</p>
        <p style="margin:4px 0;">zgrok reverse tunnel server</p>
    </div>
</body>
</html>"""
    return web.Response(status=200, content_type="text/html", text=html)

async def switch_handler(request: web.Request) -> web.Response:
    """Endpoint amigável (/switch ou /zgrok-switch) para alternar entre túneis ativos."""
    to_tunnel = request.query.get("to", "").strip().lower()
    if to_tunnel and to_tunnel in active_tunnels:
        redirect_res = web.Response(status=302, headers={"Location": "/"})
        redirect_res.set_cookie(
            name="zgrok_tunnel",
            value=to_tunnel,
            path="/",
            samesite="Lax",
            max_age=86400 * 30
        )
        return redirect_res

    if not active_tunnels:
        return web.Response(
            status=503,
            content_type="text/html",
            text="""<!DOCTYPE html>
<html lang="pt-BR">
<head><title>zgrok - Nenhum Túnel Ativo</title><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="font-family:sans-serif;text-align:center;padding:50px 20px;background:#0f172a;color:#e2e8f0;">
    <h1 style="color:#ef4444;margin-bottom:12px;">503 - Nenhum Túnel Ativo</h1>
    <p style="color:#94a3b8;font-size:16px;">Nenhum cliente zgrok está conectado no momento.</p>
    <p style="color:#64748b;font-size:13px;margin-top:25px;">Inicie o cliente zgrok no seu computador para conectar o túnel.</p>
</body>
</html>"""
        )
    return render_tunnel_selector(request)

async def http_proxy_handler(request: web.Request) -> web.Response:
    """
    Recebe requisições com prefixo /zgrok/{tunnel_id} e:
    1. Se for navegação do usuário (GET na raiz do túnel /zgrok/{id}/ ou página html),
       grava o cookie de sessão e redireciona (302) para a raiz '/', evitando erros 404 em SPAs.
    2. Se for chamada direta de API / Webhook, repassa diretamente ao túnel.
    """
    tunnel_id = request.match_info.get("tunnel_id", "").lower()
    subpath = request.match_info.get("subpath", "")
    
    if tunnel_id not in active_tunnels:
        return render_tunnel_not_found(tunnel_id)

    accept = request.headers.get("Accept", "")
    is_browser_nav = request.method == "GET" and (subpath in ("", "/") or "text/html" in accept)
    
    if is_browser_nav:
        target_path = "/"
        if subpath and subpath not in ("", "/"):
            target_path = f"/{subpath.lstrip('/')}"
        if request.query_string:
            sep = "&" if "?" in target_path else "?"
            target_path = f"{target_path}{sep}{request.query_string}"

        redirect_res = web.Response(
            status=302,
            headers={"Location": target_path}
        )
        redirect_res.set_cookie(
            name="zgrok_tunnel",
            value=tunnel_id,
            path="/",
            samesite="Lax",
            max_age=86400 * 30
        )
        return redirect_res

    return await forward_to_tunnel(tunnel_id, subpath, request)

async def root_proxy_handler(request: web.Request) -> web.Response:
    """Recebe requisições na raiz / e repassa ao túnel correto."""
    # 1. Identificar se o primeiro segmento da URL é o ID de um túnel (ex: /frontend ou /meu-app/)
    path_clean = request.path.strip("/")
    parts = path_clean.split("/", 1) if path_clean else []
    first_part = parts[0].lower() if parts else ""

    if first_part and first_part in active_tunnels:
        tunnel_id = first_part
        subpath = parts[1] if len(parts) > 1 else ""

        accept = request.headers.get("Accept", "")
        is_browser_nav = request.method == "GET" and (subpath in ("", "/") or "text/html" in accept)

        if is_browser_nav:
            target_path = "/"
            if subpath and subpath not in ("", "/"):
                target_path = f"/{subpath.lstrip('/')}"
            if request.query_string:
                sep = "&" if "?" in target_path else "?"
                target_path = f"{target_path}{sep}{request.query_string}"

            redirect_res = web.Response(
                status=302,
                headers={"Location": target_path}
            )
            redirect_res.set_cookie(
                name="zgrok_tunnel",
                value=tunnel_id,
                path="/",
                samesite="Lax",
                max_age=86400 * 30
            )
            return redirect_res

        # Para chamadas diretas de APIs / Webhooks com ID (ex: POST /frontend/api/...)
        return await forward_to_tunnel(tunnel_id, subpath, request)

    # 2. Identificar túnel pelo subdomínio (ex: 74jj5d.zgrok.meudominio.com)
    host_clean = request.host.split(":")[0].lower()
    sub_parts = host_clean.split(".")
    if sub_parts and sub_parts[0] in active_tunnels:
        return await forward_to_tunnel(sub_parts[0], request.path, request)

    # 3. Cookie de sessão do túnel (quando o usuário ativou o túnel ou selecionou na tela)
    cookie_id = request.cookies.get("zgrok_tunnel", "").strip().lower()
    if cookie_id and cookie_id in active_tunnels:
        return await forward_to_tunnel(cookie_id, request.path, request)

    # 4. Referer do túnel
    referer = request.headers.get("Referer", "")
    for tid in active_tunnels:
        if f"/zgrok/{tid}" in referer or f"{tid}." in referer or f"/{tid}/" in referer:
            return await forward_to_tunnel(tid, request.path, request)

    # 5. Túnel com ID fixo configurado no servidor
    fixed_id = config.get("fixed_tunnel_id", "").strip().lower()
    if fixed_id and fixed_id in active_tunnels:
        return await forward_to_tunnel(fixed_id, request.path, request)

    # 6. Se houver apenas 1 túnel ativo no servidor, atalha direto para ele
    if len(active_tunnels) == 1:
        tunnel_id = list(active_tunnels.keys())[0]
        return await forward_to_tunnel(tunnel_id, request.path, request)

    # 7. Se houver múltiplos túneis conectados e a requisição não identificou o túnel
    if len(active_tunnels) > 1:
        return render_tunnel_selector(request)

    return web.Response(
        status=503,
        content_type="text/html",
        text="""<!DOCTYPE html>
<html lang="pt-BR">
<head><title>zgrok - Nenhum Túnel Ativo</title><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="font-family:sans-serif;text-align:center;padding:50px 20px;background:#0f172a;color:#e2e8f0;">
    <h1 style="color:#ef4444;margin-bottom:12px;">503 - Nenhum Túnel Ativo</h1>
    <p style="color:#94a3b8;font-size:16px;">Nenhum cliente zgrok está conectado no momento.</p>
    <p style="color:#64748b;font-size:13px;margin-top:25px;">Inicie o cliente zgrok no seu computador para conectar o túnel.</p>
</body>
</html>"""
    )

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
    # Rota para chaveamento/seleção de múltiplos túneis
    app.router.add_get("/switch", switch_handler)
    app.router.add_get("/zgrok-switch", switch_handler)
    app.router.add_get("/zgrok-select", switch_handler)
    app.router.add_get("/zgrok", switch_handler)
    app.router.add_get("/zgrok/", switch_handler)
    # Rota pública por path (/zgrok/{tunnel_id}/...)
    app.router.add_route("*", "/zgrok/{tunnel_id}", http_proxy_handler)
    app.router.add_route("*", "/zgrok/{tunnel_id}/{subpath:.*}", http_proxy_handler)
    # Rota pública raiz para subdomínio dedicado (ngrok-style, ex: zgrok.meudominio.com/api/...)
    app.router.add_route("*", "/{subpath:.*}", root_proxy_handler)
    return app

if __name__ == "__main__":
    app = create_app()
    host = config.get("host", "0.0.0.0")
    port = int(config.get("port", 8080))
    logger.info(f"Iniciando zgrok-server em http://{host}:{port}")
    web.run_app(app, host=host, port=port)
