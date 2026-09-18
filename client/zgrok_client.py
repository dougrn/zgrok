#!/usr/bin/env python3
"""
zgrok - Cliente CLI de Túnel Reverso Pessoal
Conecta à VPS e encaminha o tráfego externo para a porta local.
Exemplo de uso:
    python zgrok.py http 3000
    python zgrok.py 3000
"""

import argparse
import asyncio
import base64
import json
import os
import sys
import time
from datetime import datetime
import aiohttp

# Configurar suporte a cores ANSI e UTF-8 no Windows
def setup_windows_console():
    if os.name == "nt":
        # 1. Colorama faz a conversão direta de ANSI para chamadas do console Win32
        try:
            import colorama
            colorama.init(autoreset=False)
        except Exception:
            pass

        # 2. Habilitar Virtual Terminal Processing no Windows
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            hStdOut = kernel32.GetStdHandle(-11)
            mode = ctypes.c_ulong()
            if kernel32.GetConsoleMode(hStdOut, ctypes.byref(mode)):
                mode.value |= 0x0004  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
                kernel32.SetConsoleMode(hStdOut, mode)
        except Exception:
            pass

        # 3. Forçar codificação UTF-8
        try:
            if hasattr(sys.stdout, "reconfigure"):
                sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

setup_windows_console()

def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")

# Configurações padrão do cliente
DEFAULT_CONFIG = {
    "server_ws_url": "ws://127.0.0.1:8080/zgrok-ws",
    "auth_token": "",
    "default_local_host": "127.0.0.1"
}

def get_possible_config_paths():
    """Retorna locais prováveis onde o config.json pode estar."""
    current_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(current_dir)
    user_home = os.path.expanduser("~")
    
    return [
        os.path.join(parent_dir, "config.json"),
        os.path.join(current_dir, "config.json"),
        os.path.join(user_home, ".zgrok", "config.json"),
        os.path.join(os.getcwd(), "config.json")
    ]

def load_config() -> dict:
    cfg = DEFAULT_CONFIG.copy()
    for path in get_possible_config_paths():
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    cfg.update(loaded)
                    return cfg
            except Exception as e:
                pass
    return cfg

# Estilos ANSI para terminal limpo e moderno
class Colors:
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    MAGENTA = "\033[95m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RESET = "\033[0m"

def format_status(status_code: int) -> str:
    if 200 <= status_code < 300:
        return f"{Colors.GREEN}{status_code} OK{Colors.RESET}"
    elif 300 <= status_code < 400:
        return f"{Colors.YELLOW}{status_code}{Colors.RESET}"
    elif 400 <= status_code < 500:
        return f"{Colors.RED}{status_code}{Colors.RESET}"
    else:
        return f"{Colors.RED}{Colors.BOLD}{status_code}{Colors.RESET}"

def log_request(method: str, path: str, status: int, duration_ms: float):
    now = datetime.now().strftime("%H:%M:%S")
    status_fmt = format_status(status)
    method_color = Colors.CYAN if method in ("GET", "HEAD") else Colors.MAGENTA
    print(f"{Colors.DIM}[{now}]{Colors.RESET} {method_color}{method:<6}{Colors.RESET} {path:<40} {status_fmt} {Colors.DIM}({duration_ms:.1f}ms){Colors.RESET}")

async def handle_request(req_data: dict, local_base: str, session: aiohttp.ClientSession, ws: aiohttp.ClientWebSocketResponse):
    """Encaminha a requisição recebida da VPS para o serviço local e devolve a resposta."""
    request_id = req_data.get("request_id")
    method = req_data.get("method", "GET")
    path = req_data.get("path", "/")
    headers = req_data.get("headers", {})
    body_b64 = req_data.get("body_b64", "")

    raw_body = base64.b64decode(body_b64) if body_b64 else None

    target_url = f"{local_base}{path}"
    start_time = time.time()

    try:
        async with session.request(
            method=method,
            url=target_url,
            headers=headers,
            data=raw_body,
            allow_redirects=False
        ) as resp:
            # Se deu 404 e o path tem prefixo de pasta adicionado pelo Apache (ex: /pasta/api/stats)
            # Tenta automaticamente sem o prefixo (ex: /api/stats)
            if resp.status == 404 and path.count("/") >= 2:
                parts = path.lstrip("/").split("/", 1)
                if len(parts) == 2:
                    fallback_path = "/" + parts[1]
                    fallback_url = f"{local_base}{fallback_path}"
                    async with session.request(
                        method=method,
                        url=fallback_url,
                        headers=headers,
                        data=raw_body,
                        allow_redirects=False
                    ) as fb_resp:
                        if fb_resp.status != 404:
                            resp_body = await fb_resp.read()
                            duration_ms = (time.time() - start_time) * 1000
                            resp_b64 = base64.b64encode(resp_body).decode("utf-8") if resp_body else ""
                            res_headers = dict(fb_resp.headers)
                            log_request(method, fallback_path, fb_resp.status, duration_ms)
                            await ws.send_json({
                                "type": "response",
                                "request_id": request_id,
                                "status": fb_resp.status,
                                "headers": res_headers,
                                "body_b64": resp_b64
                            })
                            return

            resp_body = await resp.read()
            duration_ms = (time.time() - start_time) * 1000
            resp_b64 = base64.b64encode(resp_body).decode("utf-8") if resp_body else ""
            res_headers = dict(resp.headers)

            log_request(method, path, resp.status, duration_ms)

            await ws.send_json({
                "type": "response",
                "request_id": request_id,
                "status": resp.status,
                "headers": res_headers,
                "body_b64": resp_b64
            })
    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        log_request(method, path, 502, duration_ms)
        print(f"    {Colors.RED}└─ Erro ao conectar ao servidor local: {e}{Colors.RESET}")

        await ws.send_json({
            "type": "response",
            "request_id": request_id,
            "status": 502,
            "headers": {"Content-Type": "text/plain; charset=utf-8"},
            "body_b64": base64.b64encode(f"502 Bad Gateway: falha ao conectar no host local ({e})".encode("utf-8")).decode("utf-8")
        })

async def run_tunnel(port: int, local_host: str, server_ws: str, token: str, requested_id: str = ""):
    local_base = f"http://{local_host}:{port}"
    reconnect_delay = 3

    params = []
    if token:
        params.append(f"token={token}")
    if requested_id:
        params.append(f"id={requested_id}")
    query = f"?{'&'.join(params)}" if params else ""
    full_ws_url = f"{server_ws}{query}"

    while True:
        try:
            print(f"\n{Colors.DIM}[*] Conectando ao servidor zgrok ({server_ws})...{Colors.RESET}")
            async with aiohttp.ClientSession() as http_client:
                async with http_client.ws_connect(full_ws_url, heartbeat=15.0) as ws:
                    init_msg = await ws.receive_json(timeout=10.0)
                    if init_msg.get("type") == "error":
                        print(f"{Colors.RED}[!] Erro do servidor: {init_msg.get('message')}{Colors.RESET}")
                        return

                    tunnel_id = init_msg.get("tunnel_id", "")
                    public_url = init_msg.get("public_url", "")

                    # Renderizar painel no estilo ngrok com suporte nativo
                    clear_screen()
                    print(f"{Colors.CYAN}{Colors.BOLD}zgrok{Colors.RESET} - Túnel Reverso Pessoal\n")
                    print(f"  {Colors.BOLD}Status:{Colors.RESET}        {Colors.GREEN}[Online]{Colors.RESET}")
                    print(f"  {Colors.BOLD}Túnel ID:{Colors.RESET}      {Colors.YELLOW}{tunnel_id}{Colors.RESET}")
                    print(f"  {Colors.BOLD}Forwarding:{Colors.RESET}    {Colors.GREEN}{Colors.BOLD}{public_url}{Colors.RESET} -> {Colors.CYAN}{local_base}{Colors.RESET}")
                    print(f"  {Colors.BOLD}Servidor VPS:{Colors.RESET}  {server_ws}")
                    print(f"\n{Colors.DIM}{'-' * 70}{Colors.RESET}")
                    print(f"{Colors.BOLD}{'HORA':<10} {'METODO':<7} {'PATH':<38} {'STATUS':<14} {'DURACAO'}{Colors.RESET}")
                    print(f"{Colors.DIM}{'-' * 70}{Colors.RESET}")

                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            payload = json.loads(msg.data)
                            if payload.get("type") == "request":
                                asyncio.create_task(
                                    handle_request(payload, local_base, http_client, ws)
                                )
                        elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                            break

        except aiohttp.ClientConnectorError as e:
            print(f"{Colors.RED}[!] Falha de conexão com a VPS: {e}{Colors.RESET}")
        except asyncio.TimeoutError:
            print(f"{Colors.RED}[!] Timeout de comunicação com o servidor.{Colors.RESET}")
        except Exception as e:
            print(f"{Colors.RED}[!] Conexão interrompida: {e}{Colors.RESET}")

        print(f"{Colors.DIM}[*] Tentando reconectar em {reconnect_delay} segundos... (Ctrl+C para sair){Colors.RESET}")
        await asyncio.sleep(reconnect_delay)

def parse_args():
    parser = argparse.ArgumentParser(
        description="zgrok - Túnel reverso pessoal (alternativa ngrok)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Exemplos:\n  zgrok http 3000\n  zgrok 3000\n  zgrok 5010"
    )

    parser.add_argument("protocol_or_port", help="Protocolo ('http') ou porta local diretamente (ex: 3000)")
    parser.add_argument("port", nargs="?", type=int, default=None, help="Porta local quando o protocolo é informado (ex: 3000)")
    parser.add_argument("--host", default=None, help="Host local de destino (padrão: 127.0.0.1)")
    parser.add_argument("--server", default=None, help="Endereço WebSocket do servidor zgrok (ex: wss://meudominio.com/zgrok-ws)")
    parser.add_argument("--token", default=None, help="Token de autenticação configurado no servidor")
    parser.add_argument("--id", default="", help="ID customizado para o túnel (opcional, por padrão é gerado automaticamente)")

    return parser.parse_args()

def main():
    args = parse_args()
    config = load_config()

    if args.protocol_or_port.isdigit():
        local_port = int(args.protocol_or_port)
    elif args.port is not None:
        local_port = args.port
    else:
        print(f"{Colors.RED}Erro: Porta local inválida.{Colors.RESET}")
        print("Uso correto: zgrok http 3000  OU  zgrok 3000")
        sys.exit(1)

    local_host = args.host or config.get("default_local_host", "127.0.0.1")
    server_ws = args.server or config.get("server_ws_url", "ws://127.0.0.1:8080/zgrok-ws")
    token = args.token if args.token is not None else config.get("auth_token", "")

    try:
        asyncio.run(run_tunnel(
            port=local_port,
            local_host=local_host,
            server_ws=server_ws,
            token=token,
            requested_id=args.id
        ))
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}[*] zgrok encerrado.{Colors.RESET}")

if __name__ == "__main__":
    main()
