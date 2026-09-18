#!/usr/bin/env python3
"""
zgrok - Atalho principal
Permite executar:
    python zgrok.py http 3000
    python zgrok.py 3000
    zgrok 5010
"""
import sys
import os

# Adiciona o diretório base e o client ao path
base_dir = os.path.dirname(os.path.abspath(__file__))
client_dir = os.path.join(base_dir, "client")
if client_dir not in sys.path:
    sys.path.insert(0, client_dir)

from zgrok_client import main

if __name__ == "__main__":
    main()
