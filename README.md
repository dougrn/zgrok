<div align="center">

# ⚡ zgrok

**Túnel reverso pessoal, seguro e de código aberto — a sua própria alternativa ao ngrok.**

Exponha seus servidores locais (localhost) para a internet através da sua própria VPS, **sem precisar criar subdomínios, configurar zonas DNS wildcard ou emitir certificados SSL adicionais**, utilizando roteamento por path integrado ao Apache.

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat&logo=python&logoColor=white)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Platform](https://img.shields.io/badge/Platform-Linux%20%7C%20Windows%20%7C%20macOS-blue)](https://github.com)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com)

</div>

---

## ✨ Por que o zgrok?

O **ngrok** é excelente, mas impõe limitações em planos gratuitos: URLs que expiram, limites de requisições, telas de aviso intermediárias e obrigatoriedade de contas.

Com o **zgrok**, você roda o seu próprio serviço de túnel na sua VPS:
- 🚀 **Sem DNS Wildcard:** Não precisa criar registros `*.seudominio.com` nem gerar certificados SSL separados.
- 🎯 **IDs Automáticos:** Basta rodar `zgrok 3000` e o servidor gera um link único instantaneamente (ex: `https://meudominio.com/zgrok/a8f3k2/`).
- 🔄 **Resolução Inteligente de Rotas:** Fallback automático para evitar erros 404 em assets e chamadas de API relativas.
- 🔒 **Seguro:** Proteção com token de autenticação opcional e conexão WebSocket criptografada (WSS).
- 💻 **Zero Portas Extras no Firewall:** O cliente e os visitantes se comunicam através das portas padrão `80`/`443` do Apache.
- 🖥️ **CLI Interativa:** Painel em tempo real no terminal exibindo método, status HTTP, rota e tempo de resposta (ms).
- 📦 **Executável Windows:** Inclui script para compilar em arquivo `.exe` standalone com 1 clique.

---

## 🏛️ Arquitetura

```text
[ Visitante Externo / Webhook ] 
              │ (HTTPS - Porta 443)
              ▼
   [ Apache VPS + .htaccess ]
              │ (ProxyPass interno para localhost:8080)
              ▼
   [ zgrok-server (Python :8080) ]
              │ (Túnel WebSocket WSS persistente)
              ▼
    [ zgrok CLI / zgrok.exe (Seu Computador) ]
              │ (HTTP local)
              ▼
    [ Sua Aplicação Local (:3000, :5000, :8080) ]
```

---

## 🚀 Como Usar no Computador Local (Cliente)

### 1. Clonar o repositório e instalar dependências

```bash
git clone https://github.com/dougrn/zgrok.git
cd zgrok
pip install -r requirements.txt
```

### 2. Configurar o endereço da sua VPS

Copie o arquivo de exemplo:
```bash
cp config.example.json config.json
```

Edite o `config.json`:
```json
{
  "server_ws_url": "wss://meudominio.com/zgrok-ws",
  "auth_token": "seu_token_secreto_aqui",
  "default_local_host": "127.0.0.1"
}
```

### 3. Abrir um Túnel

Basta informar a porta local da sua aplicação:

```bash
# Sintaxe completa:
python zgrok.py http 3000

# Ou simplesmente a porta:
python zgrok.py 3000

# Ou se compilou o .exe (Windows):
zgrok 3000
```

### Painel no Terminal:
```text
zgrok - Túnel Reverso Pessoal

  Status:        [Online]
  Túnel ID:      h01s1v
  Forwarding:    https://meudominio.com/zgrok/h01s1v/ -> http://127.0.0.1:3000
  Servidor VPS:  wss://meudominio.com/zgrok-ws

----------------------------------------------------------------------
HORA       METODO  PATH                                   STATUS         DURACAO
----------------------------------------------------------------------
[17:38:54] GET    /                                        200 OK         (3.0ms)
[17:38:55] GET    /api/stats                               200 OK         (2.5ms)
[17:38:56] POST   /api/webhook                             200 OK         (12.4ms)
```

---

## 🛠️ Instalação na VPS (Servidor)

### 1. Pré-requisitos na VPS (Ubuntu / Debian)

```bash
sudo apt update
sudo apt install -y python3 python3-pip apache2
sudo a2enmod rewrite proxy proxy_http proxy_wstunnel
sudo systemctl restart apache2
```

### 2. Clonar e configurar o servidor

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
  "auth_token": "seu_token_secreto_aqui",
  "public_url_prefix": "https://meudominio.com/zgrok",
  "request_timeout": 30,
  "id_length": 6
}
```

### 3. Configurar o Apache

Você pode colocar as regras no seu `.htaccess` ou direto no VirtualHost do seu domínio com SSL.

#### Opção Recomendada: Direto no VirtualHost SSL (`/etc/apache2/sites-available/...-ssl.conf`)
Adicione antes de `</VirtualHost>`:

```apache
# zgrok - Conexão WebSocket para o cliente local
ProxyPass /zgrok-ws ws://127.0.0.1:8080/zgrok-ws
ProxyPassReverse /zgrok-ws ws://127.0.0.1:8080/zgrok-ws

# zgrok - Roteamento público dos túneis
ProxyPass /zgrok http://127.0.0.1:8080/zgrok
ProxyPassReverse /zgrok http://127.0.0.1:8080/zgrok

# zgrok - Status do servidor
ProxyPass /zgrok-status http://127.0.0.1:8080/zgrok-status
ProxyPassReverse /zgrok-status http://127.0.0.1:8080/zgrok-status
```

#### Opção via `.htaccess`
Se preferir usar `.htaccess`, copie o arquivo de [apache/.htaccess](apache/.htaccess) para a raiz do seu site:
```bash
sudo cp apache/.htaccess /var/www/html/.htaccess
```

### 4. Rodar como Serviço no Linux (24/7 via Systemd)

```bash
sudo cp server/zgrok.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now zgrok
sudo systemctl restart apache2
```

Verifique o status do serviço:
```bash
sudo systemctl status zgrok
```

---

## 🪟 Como Gerar o Executável para Windows (`zgrok.exe`)

Se você usa Windows e deseja um arquivo executável autônomo sem precisar chamar `python zgrok.py`:

Basta executar o script:
```cmd
build.bat
```
Ou manualmente com o PyInstaller:
```bash
pip install pyinstaller colorama
python -m PyInstaller --onefile --clean --name zgrok --paths client --hidden-import colorama zgrok.py
```

O arquivo `zgrok.exe` será gerado pronto para uso. Para poder chamar de qualquer lugar, basta adicionar a pasta ao seu **PATH** do Windows!

---

## 🧪 Testes Automatizados

O projeto inclui suíte completa de testes de integração ponta a ponta:

```bash
python -m unittest tests/test_zgrok.py
```

Os testes validam:
- Inicialização do servidor e cliente em background.
- Handshake WebSocket com geração automática de IDs.
- Roteamento completo de requisições HTTP GET e POST (com payloads JSON).
- Retorno de status codes adequados (200, 201, 404 para túneis offline).

---

## 📂 Estrutura de Diretórios

```text
zgrok/
├── apache/
│   ├── .htaccess             # Regras de rewrite / proxy para o Apache
│   └── gateway.php           # Fallback em PHP para hosts restritos
├── client/
│   ├── zgrok_client.py       # Motor do cliente CLI e túnel WebSocket
│   ├── zgrok.py              # Atalho de importação
│   └── config.example.json   # Configuração de exemplo do cliente
├── server/
│   ├── server.py             # Servidor Python assíncrono (aiohttp)
│   ├── config.example.json   # Configuração de exemplo do servidor
│   └── zgrok.service         # Arquivo de serviço systemd para a VPS
├── tests/
│   └── test_zgrok.py         # Testes de integração ponta a ponta
├── .gitignore                # Protege tokens, configs locais e binários
├── build.bat                 # Script de compilação do .exe para Windows
├── config.example.json       # Exemplo de configuração na raiz
├── LICENSE                   # Licença MIT
├── README.md                 # Documentação completa
├── requirements.txt          # Dependências do projeto
├── zgrok.bat                 # Executável para prompt do Windows
└── zgrok.py                  # Ponto de entrada da CLI
```

---

## 📄 Licença

Este projeto está sob a licença [MIT](LICENSE). Sinta-se livre para usar, modificar e distribuir.
