#!/usr/bin/env python3
"""
Testes automatizados de ponta a ponta para o zgrok:
- Sobe o zgrok-server em background
- Sobe um servidor HTTP local simulado
- Conecta o zgrok-client
- Realiza requisições GET e POST pelo túnel
- Valida integridade das respostas e status codes
"""

import asyncio
import json
import time
import unittest
from aiohttp import web, ClientSession

# Importa o app do servidor
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "client"))

from server import create_app
import zgrok

class TestZgrokTunnel(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        # 1. Iniciar servidor simulado local (onde a aplicação do dev roda)
        local_app = web.Application()
        async def hello_handler(req):
            return web.json_response({"message": "hello from local app", "method": req.method})
        
        async def echo_post_handler(req):
            body = await req.json()
            return web.json_response({"received": body, "status": "success"}, status=201)

        local_app.router.add_get("/test", hello_handler)
        local_app.router.add_post("/api/data", echo_post_handler)

        self.local_runner = web.AppRunner(local_app)
        await self.local_runner.setup()
        self.local_site = web.TCPSite(self.local_runner, "127.0.0.1", 13000)
        await self.local_site.start()

        # 2. Iniciar o zgrok-server na porta 18080
        server_app = create_app()
        self.server_runner = web.AppRunner(server_app)
        await self.server_runner.setup()
        self.server_site = web.TCPSite(self.server_runner, "127.0.0.1", 18080)
        await self.server_site.start()

    async def asyncTearDown(self):
        await self.local_runner.cleanup()
        await self.server_runner.cleanup()

    async def test_end_to_end_tunnel(self):
        # Iniciar o cliente zgrok em uma task assíncrona
        tunnel_task = asyncio.create_task(
            zgrok.run_tunnel(
                port=13000,
                local_host="127.0.0.1",
                server_ws="ws://127.0.0.1:18080/zgrok-ws",
                token="",
                requested_id="testrun"
            )
        )

        # Aguardar 1 segundo para conexão estabelecer
        await asyncio.sleep(1.0)

        async with ClientSession() as session:
            # 1. Testar GET através da rota do túnel
            tunnel_url = "http://127.0.0.1:18080/zgrok/testrun/test"
            async with session.get(tunnel_url) as resp:
                self.assertEqual(resp.status, 200)
                data = await resp.json()
                self.assertEqual(data.get("message"), "hello from local app")
                self.assertEqual(data.get("method"), "GET")

            # 2. Testar POST com JSON através do túnel
            post_url = "http://127.0.0.1:18080/zgrok/testrun/api/data"
            payload = {"item": "notebook", "qty": 3}
            async with session.post(post_url, json=payload) as resp:
                self.assertEqual(resp.status, 201)
                data = await resp.json()
                self.assertEqual(data.get("status"), "success")
                self.assertEqual(data.get("received"), payload)

            # 3. Testar túnel inexistente -> deve retornar 404
            invalid_url = "http://127.0.0.1:18080/zgrok/inexistente/test"
            async with session.get(invalid_url) as resp:
                self.assertEqual(resp.status, 404)

        tunnel_task.cancel()
        try:
            await tunnel_task
        except asyncio.CancelledError:
            pass

    async def test_automatic_id_generation(self):
        # Conectar sem passar ID (id="")
        tunnel_task = asyncio.create_task(
            zgrok.run_tunnel(
                port=13000,
                local_host="127.0.0.1",
                server_ws="ws://127.0.0.1:18080/zgrok-ws",
                token="",
                requested_id=""
            )
        )

        await asyncio.sleep(1.0)

        # Deve haver 1 túnel ativo no servidor com ID de 6 caracteres
        from server import active_tunnels
        self.assertEqual(len(active_tunnels), 1)
        auto_id = list(active_tunnels.keys())[0]
        self.assertEqual(len(auto_id), 6)

        async with ClientSession() as session:
            test_url = f"http://127.0.0.1:18080/zgrok/{auto_id}/test"
            async with session.get(test_url) as resp:
                self.assertEqual(resp.status, 200)
                data = await resp.json()
                self.assertEqual(data.get("message"), "hello from local app")

        tunnel_task.cancel()
        try:
            await tunnel_task
        except asyncio.CancelledError:
            pass

if __name__ == "__main__":
    unittest.main()
