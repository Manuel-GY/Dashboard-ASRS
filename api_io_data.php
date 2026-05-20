<?php
header('Content-Type: application/json');

// Bypass proxy or just get the page
$opts = [
    "http" => [
        "method" => "GET",
        "header" => "Accept-language: en\r\n",
        "timeout" => 5
    ]
];
$context = stream_context_create($opts);
$html = @file_get_contents("http://10.107.194.62/sbs/gtasrs_dashboard/gtasrs_dashboard_ctrl.php", false, $context);

if ($html === FALSE) {
    http_response_code(500);
    echo json_encode(["error" => "Failed to fetch data from remote server"]);
    exit;
}

function extract_val($id_name, $html) {
    if (preg_match("/getElementById\('$id_name'\)\.innerHTML\s*=\s*'([^']+)'/", $html, $matches)) {
        return $matches[1];
    }
    return "0";
}

$data = [
    "entrada" => extract_val("s1_inbound_total", $html),
    "manual" => extract_val("s1_outbound_cv31_actual", $html),
    "auto" => extract_val("s1_press_total", $html),
    "rate_entrada" => extract_val("s1_inbound_avg", $html),
    "rate_manual" => extract_val("s1_manual_rate", $html),
    "rate_auto" => extract_val("s1_press_rate", $html)
];

echo json_encode($data);
?>
