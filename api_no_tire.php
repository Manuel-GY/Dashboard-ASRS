<?php
header('Content-Type: application/json');

// Get custom date ranges or default to last 24 hours
$start = $_GET['start'] ?? '';
$end = $_GET['end'] ?? '';

try {
    if ($start) {
        $start_dt = new DateTime($start);
    } else {
        $start_dt = new DateTime();
        $start_dt->modify('-24 hours');
    }

    if ($end) {
        $end_dt = new DateTime($end);
    } else {
        $end_dt = new DateTime();
    }
} catch (Exception $e) {
    http_response_code(400);
    echo json_encode(["error" => "Formatos de fecha inválidos. Use YYYY-MM-DDTHH:mm"]);
    exit;
}

$start_formatted = $start_dt->format('Y/m/d H:i:s');
$end_formatted = $end_dt->format('Y/m/d H:i:s');

// Build internal API URL
$baseUrl = "http://10.107.194.85:8080/ProductionWebEditServerRS/ReportService/all_areas/counts/Reports/SummaryDataByReason/SingleDowntimeReason.EditGrid/EditGrid/DataSource/loadId";
$params = [
    "ARG_MACH_TYPE" => "PRS",
    "ARG_MACH_PART_NAME" => "",
    "ARG_DOWNTIME_REASON" => "160000", // No Tire Downtime Reason code
    "ARG_START_DATE" => $start_formatted,
    "ARG_END_DATE" => $end_formatted,
    "ARG_LANG" => "ENG",
    "ARG_MACHINE_GROUP_GUID" => ""
];

$url = $baseUrl . "?" . http_build_query($params);

$opts = [
    "http" => [
        "method" => "GET",
        "header" => "Accept-language: en\r\n",
        "timeout" => 8
    ]
];
$context = stream_context_create($opts);
$response = @file_get_contents($url, false, $context);

if ($response === FALSE) {
    http_response_code(500);
    echo json_encode([
        "error" => "No se pudo conectar al servidor de reportes interno (10.107.194.85)",
        "query_url" => $url
    ]);
    exit;
}

// Disable entity loader for security
if (function_exists('libxml_disable_entity_loader')) {
    @libxml_disable_entity_loader(true);
}

$xml = @simplexml_load_string($response);
if ($xml === FALSE) {
    http_response_code(500);
    echo json_encode([
        "error" => "Error al procesar la respuesta XML del servidor de reportes",
        "raw_response_snippet" => substr($response, 0, 500)
    ]);
    exit;
}

$downtime_by_group = [
    "100A" => 0, "100B" => 0,
    "200A" => 0, "200B" => 0,
    "300A" => 0, "300B" => 0,
    "400A" => 0, "400B" => 0,
    "500A" => 0, "500B" => 0,
    "600A" => 0, "600B" => 0
];

if (isset($xml->Row)) {
    foreach ($xml->Row as $row) {
        $mach = (string)$row->MACH_PART_NAME;
        $down_time = (float)$row->DOWN_TIME;
        
        // Map press name to line and side
        // Example: '107' -> line '100', number '07'
        if (preg_match('/^([1-6])(\d+)$/', $mach, $matches)) {
            $line = $matches[1] . '00';
            $num = intval($matches[2]);
            
            // Side A: Odd numbers. Side B: Even numbers.
            $side = ($num % 2 !== 0) ? 'A' : 'B';
            $group = $line . $side;
            
            if (isset($downtime_by_group[$group])) {
                $downtime_by_group[$group] += $down_time;
            }
        }
    }
}

// Calculate durations and percentages
$duration_seconds = $end_dt->getTimestamp() - $start_dt->getTimestamp();
$duration_minutes = max(1, round($duration_seconds / 60));

$total_downtime = array_sum($downtime_by_group);

// 48 presses in total (6 lines * 8 presses)
// Downtime % = (Total downtime mins / (Total period mins * 48 presses)) * 100
$num_presses = 48;
$total_available_minutes = $duration_minutes * $num_presses;
$downtime_percent = ($total_downtime / $total_available_minutes) * 100;

// Round all values for clean presentation
foreach ($downtime_by_group as $g => $val) {
    $downtime_by_group[$g] = round($val, 2);
}

echo json_encode([
    "success" => true,
    "query_start" => $start_formatted,
    "query_end" => $end_formatted,
    "duration_minutes" => $duration_minutes,
    "downtime_by_group" => $downtime_by_group,
    "total_downtime" => round($total_downtime, 2),
    "downtime_percent" => round($downtime_percent, 2)
]);
?>
