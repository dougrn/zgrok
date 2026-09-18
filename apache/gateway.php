<?php
/**
 * zgrok - Gateway / Proxy reverso em PHP (Fallback)
 * 
 * Utilize este arquivo se o Apache da sua VPS não permitir a flag [P] (ProxyPass)
 * diretamente no arquivo .htaccess.
 * 
 * Regra correspondente no .htaccess:
 * RewriteRule ^zgrok/(.*)$ gateway.php?_zgrok_path=$1 [QSA,L]
 */

declare(strict_types=1);

$backendHost = 'http://127.0.0.1:8080';
$path = isset($_GET['_zgrok_path']) ? $_GET['_zgrok_path'] : '';

// Limpar parâmetro interno
$queryParams = $_GET;
unset($queryParams['_zgrok_path']);
$queryString = http_build_query($queryParams);

$targetUrl = rtrim($backendHost, '/') . '/zgrok/' . ltrim($path, '/');
if (!empty($queryString)) {
    $targetUrl .= '?' . $queryString;
}

$ch = curl_init($targetUrl);

$requestMethod = $_SERVER['REQUEST_METHOD'] ?? 'GET';
curl_setopt($ch, CURLOPT_CUSTOMREQUEST, $requestMethod);
curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
curl_setopt($ch, CURLOPT_HEADER, true);
curl_setopt($ch, CURLOPT_TIMEOUT, 60);

// Repassar corpo (POST, PUT, PATCH, etc.)
$requestBody = file_get_contents('php://input');
if (!empty($requestBody)) {
    curl_setopt($ch, CURLOPT_POSTFIELDS, $requestBody);
}

// Repassar headers recebidos
$headers = [];
foreach (getallheaders() as $name => $value) {
    $lower = strtolower($name);
    if (!in_array($lower, ['host', 'content-length', 'transfer-encoding', 'connection'])) {
        $headers[] = "$name: $value";
    }
}
$headers[] = 'X-Forwarded-For: ' . ($_SERVER['REMOTE_ADDR'] ?? '');
$headers[] = 'X-Forwarded-Proto: ' . ((isset($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off') ? 'https' : 'http');
curl_setopt($ch, CURLOPT_HTTPHEADER, $headers);

$response = curl_exec($ch);

if ($response === false) {
    http_response_code(502);
    header('Content-Type: text/plain; charset=utf-8');
    echo '502 Bad Gateway: O servidor zgrok local (Python) não está respondendo.';
    curl_close($ch);
    exit;
}

$headerSize = curl_getinfo($ch, CURLINFO_HEADER_SIZE);
$httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
curl_close($ch);

$responseHeaders = substr($response, 0, $headerSize);
$responseBody = substr($response, $headerSize);

http_response_code($httpCode);

// Enviar cabeçalhos de resposta
$headerLines = explode("\r\n", $responseHeaders);
foreach ($headerLines as $line) {
    if (empty($line) || stripos($line, 'HTTP/') === 0) {
        continue;
    }
    if (stripos($line, 'Transfer-Encoding:') === 0) {
        continue;
    }
    header($line, false);
}

echo $responseBody;
