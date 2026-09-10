<?php
header('Content-Type: text/html; charset=utf-8');
header('Cache-Control: no-store');

$state = $_GET['state'] ?? '';
if (!preg_match('/^[A-Za-z0-9_-]{20,200}$/', $state)) {
    http_response_code(400);
    echo '<h2>Invalid OAuth state.</h2>';
    exit;
}

$payload = [
    'state' => $state,
    'code' => $_GET['code'] ?? null,
    'error' => $_GET['error'] ?? null,
    'error_description' => $_GET['error_description'] ?? null,
    'created_at' => time(),
];

$dir = sys_get_temp_dir() . '/starchatter-oauth';
if (!is_dir($dir) && !mkdir($dir, 0700, true) && !is_dir($dir)) {
    http_response_code(500);
    echo '<h2>Unable to store OAuth callback.</h2>';
    exit;
}

$file = $dir . '/' . $state . '.json';
if (file_put_contents($file, json_encode($payload), LOCK_EX) === false) {
    http_response_code(500);
    echo '<h2>Unable to store OAuth callback.</h2>';
    exit;
}
@chmod($file, 0600);

if (!empty($payload['error'])) {
    $message = htmlspecialchars($payload['error_description'] ?: $payload['error'], ENT_QUOTES, 'UTF-8');
    echo '<h2>OAuth authorization failed</h2><p>' . $message . '</p><p>You can return to Telegram now.</p>';
    exit;
}

echo '<h2>OAuth authorization received ✅</h2><p>Return to Telegram and press <strong>Check Authorization</strong>.</p>';
