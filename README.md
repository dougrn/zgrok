<div align="center">

# ⚡ zgrok

**Túnel reverso pessoal, seguro e de código aberto — a sua própria alternativa ao ngrok.**

Exponha aplicações locais (`localhost`) para a internet através da sua própria VPS com Apache e SSL, encapsulando requisições na raiz (estilo ngrok) ou por rotas dedicadas.

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat&logo=python&logoColor=white)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Platform](https://img.shields.io/badge/Platform-Linux%20%7C%20Windows-blue)](https://github.com)

</div>

---

## ✨ Recursos

- 🎯 **Múltiplos Túneis Simultâneos:** Abra quantos túneis quiser ao mesmo tempo, cada um com seu ID único (gerado automaticamente ou customizado via `--id`).
- 🚀 **Roteamento Inteligente de Rotas & APIs:** Suporta `/api/...`, SPAs, arquivos estáticos e webhooks sem conflito de rotas através de cookies de sessão e roteamento inteligente.
- ⚡ **Atalho Direto & Dashboard:** Se houver apenas 1 túnel ativo, o acesso direto à raiz (`https://zgrok.meudominio.com/`) atalha automaticamente para ele. Se houver múltiplos, exibe uma tela visual para seleção.
- 🌐 **Compatível com Subdomínio Wildcard:** Suporte nativo a `https://{id}.zgrok.meudominio.com/` estilo ngrok se configurado no DNS/Apache.
- 🔒 **Seguro:** Conexão persistente criptografada via WebSocket (WSS) com suporte a token de autenticação opcional.
- 💻 **Zero Portas Extras no Firewall:** O tráfego passa pelas portas padrão `80`/`443` gerenciadas pelo Apache na VPS.
- 🖥️ **Painel em Tempo Real:** Terminal interativo com método HTTP, rota chamada, status code colorido e tempo de resposta (ms).
- 📦 **Executável Windows:** Inclui `zgrok.exe` standalone pré-compilado e script `build.bat` para recompilar com 1 clique.

---

## 🏛️ Arquitetura

```text
[ Visitante Externo / API / Webhook ] 
                  │ (HTTPS - 443)
                  ▼
         [ Apache VirtualHost ]
                  │ (ProxyPass interno para :8080)
                  ▼
       [ zgrok-server (Python :8080) ]
                  │ (Túnel WebSocket WSS persistente)
                  ▼
        [ zgrok CLI / zgrok.exe ]
                  │ (HTTP local)
                  ▼
      [ Sua Aplicação Local (:3000, :5010, etc.) ]
```

---

## 📁 Estrutura do Projeto

```text
zgrok/
├── apache/
│   └── zgrok.conf.example    # VirtualHost do Apache pronto para uso com SSL
├── client/
│   ├── zgrok.py              # Código-fonte do cliente CLI
│   ├── build.bat             # Compilador do executável Windows (.exe)
│   └── config.example.json   # Modelo de configuração do cliente
├── server/
│   ├── server.py             # Servidor assíncrono (aiohttp)
│   ├── zgrok.service         # Arquivo systemd para rodar 24/7 na VPS
│   └── config.example.json   # Modelo de configuração do servidor
├── tests/
│   └── test_zgrok.py         # Testes automatizados ponta a ponta (unittest)
├── zgrok.exe                 # Executável Windows compilado e pronto para uso
├── requirements.txt          # Dependências do projeto
├── LICENSE                   # Licença MIT
└── README.md                 # Esta documentação
```

---

## 🚀 Guia Rápido: Como Usar no Cliente (Seu Computador)

### Opção A: Usando o Executável (`zgrok.exe`)
1. Copie o arquivo `zgrok.exe` e crie um `config.json` na mesma pasta:
```json
{
  "server_ws_url": "wss://zgrok.seudominio.com/zgrok-ws",
  "auth_token": "seu_token_aqui_ou_vazio",
  "default_local_host": "127.0.0.1"
}
```

2. No terminal (CMD ou PowerShell), execute informando a porta local:
```powershell
# Porta local direta (gera ID automático):
.\zgrok.exe 3000

# Ou definindo um ID fixo customizado:
.\zgrok.exe 5010 --id 74jj5d
```

> 💡 **Dica de Múltiplos Túneis:** Você pode abrir múltiplos terminais ao mesmo tempo para diferentes portas locais (ex: um túnel para porta `3000` com `--id frontend` e outro para porta `5010` com `--id backend`). Cada um terá seu link exclusivo!

---

### Opção B: Executando com Python
```bash
# 1. Instalar dependências
pip install -r requirements.txt

# 2. Configurar o cliente
cp client/config.example.json client/config.json

# 3. Iniciar o túnel
python client/zgrok.py 3000 --id meu-app
```

### Painel no Terminal:
```text
zgrok - Túnel Reverso Pessoal

  Status:        [Online]
  Túnel ID:      74jj5d
  Forwarding:    https://zgrok.seudominio.com/zgrok/74jj5d/ -> http://127.0.0.1:5010
  Servidor VPS:  wss://zgrok.seudominio.com/zgrok-ws

----------------------------------------------------------------------
HORA       METODO  PATH                                   STATUS         DURACAO
----------------------------------------------------------------------
[11:25:47] GET    /                                        200 OK         (15.2ms)
[11:25:48] GET    /api/dados                               200 OK         (8.4ms)
[11:25:49] POST   /api/webhook                             201 OK         (24.1ms)
```

---

## 🛠️ Instalação na VPS (Servidor)

### 1. Pré-requisitos na VPS (Ubuntu / Debian)

```bash
sudo apt update
sudo apt install -y python3 python3-pip apache2
sudo a2enmod proxy proxy_http proxy_wstunnel ssl rewrite headers
sudo systemctl restart apache2
```

### 2. Clonar e Configurar o zgrok na VPS

```bash
cd /var/www/
sudo git clone https://github.com/dougrn/zgrok.git
cd /var/www/zgrok
sudo pip3 install -r requirements.txt

# Configurar o servidor
sudo cp server/config.example.json server/config.json
sudo nano server/config.json
```

Exemplo do `server/config.json`:
```json
{
  "host": "127.0.0.1",
  "port": 8080,
  "auth_token": "",
  "public_url_prefix": "https://zgrok.seudominio.com",
  "request_timeout": 30,
  "id_length": 6
}
```

### 3. Configurar o Apache (Subdomínio Dedicado)

Crie o arquivo `/etc/apache2/sites-available/zgrok.conf` (baseado em [apache/zgrok.conf.example](apache/zgrok.conf.example)):

```apache
<IfModule mod_ssl.c>
<VirtualHost *:443>
    ServerName zgrok.seudominio.com

    SSLProxyEngine On
    ProxyPreserveHost On
    ProxyRequests Off

    RequestHeader set X-Real-IP "%{REMOTE_ADDR}s"
    RequestHeader set X-Forwarded-For "%{REMOTE_ADDR}s"
    RequestHeader set X-Forwarded-Proto "https"

    # 1. Túnel WebSocket
    ProxyPass /zgrok-ws ws://127.0.0.1:8080/zgrok-ws
    ProxyPassReverse /zgrok-ws ws://127.0.0.1:8080/zgrok-ws

    # 2. Status do servidor
    ProxyPass /zgrok-status http://127.0.0.1:8080/zgrok-status
    ProxyPassReverse /zgrok-status http://127.0.0.1:8080/zgrok-status

    # 3. Encaminhamento completo da raiz para o túnel local (modo ngrok)
    ProxyPass / http://127.0.0.1:8080/
    ProxyPassReverse / http://127.0.0.1:8080/

    ErrorLog ${APACHE_LOG_DIR}/zgrok_error.log
    CustomLog ${APACHE_LOG_DIR}/zgrok_access.log combined

    Include /etc/letsencrypt/options-ssl-apache.conf
    SSLCertificateFile /etc/letsencrypt/live/zgrok.seudominio.com/fullchain.pem
    SSLCertificateKeyFile /etc/letsencrypt/live/zgrok.seudominio.com/privkey.pem
</VirtualHost>
</IfModule>
```

Ative o site e o certificado SSL:
```bash
sudo a2ensite zgrok.conf
sudo certbot --apache -d zgrok.seudominio.com
sudo apache2ctl configtest
sudo systemctl reload apache2
```

### 4. Rodar como Serviço no Linux (Systemd)

```bash
sudo cp server/zgrok.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now zgrok
```

Verifique o status do serviço:
```bash
sudo systemctl status zgrok
```

---

## 🪟 Como Compilar o `zgrok.exe` (Windows)

Para gerar uma nova versão compilada do executável:

```cmd
cd client
build.bat
```

O script utiliza o PyInstaller com a flag `--onefile` e gera o executável standalone `zgrok.exe` pronto para distribuição.

---

## 🧪 Testes Automatizados

Para rodar a suíte de testes de integração ponta a ponta:

```bash
python -m unittest tests/test_zgrok.py
```

Os testes validam:
- Inicialização do servidor assíncrono e do cliente.
- Conexão WebSocket e geração de ID automático/customizado.
- Roteamento completo de requisições GET e POST (JSON payload).
- Encapsulamento na raiz estilo ngrok (`/api/data`, `/test`).
- Status codes adequados (200, 201, 404 e 503 quando offline).

---

## 📄 Licença

Este projeto está sob a licença [MIT](LICENSE).
