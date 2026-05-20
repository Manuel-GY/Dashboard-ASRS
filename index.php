<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Dashboard ASRS</title>
    <link rel="stylesheet" href="style.css">
    <!-- Google Fonts for Modern Typography -->
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
</head>
<body>
    <!-- JavaScript Error Debug Console -->
    <div id="debug-error-console" style="display:none; position:fixed; bottom:20px; left:20px; right:20px; background:rgba(220,53,69,0.95); color:white; padding:20px; border-radius:12px; z-index:99999; font-family:monospace; font-size:13px; max-height:250px; overflow-y:auto; border:2px solid #ff6b6b; box-shadow:0 10px 30px rgba(0,0,0,0.5); backdrop-filter:blur(10px);">
        <strong style="font-size:15px; display:block; margin-bottom:8px;">⚠️ Error de JavaScript Detectado:</strong>
        <button onclick="this.parentElement.style.display='none'" style="float:right; background:white; color:#dc3545; border:none; padding:4px 10px; border-radius:6px; cursor:pointer; font-weight:bold; font-size:12px; transition:all 0.2s;">Cerrar</button>
        <div id="debug-error-list" style="white-space:pre-wrap; margin-top:10px; line-height:1.5;"></div>
    </div>
    <script>
    window.addEventListener('error', function(e) {
        var consoleDiv = document.getElementById('debug-error-console');
        var listDiv = document.getElementById('debug-error-list');
        if (consoleDiv && listDiv) {
            consoleDiv.style.display = 'block';
            listDiv.textContent += '\n• ' + e.message + '\n  en: ' + e.filename + ':' + e.lineno + ':' + e.colno + '\n';
        }
    });
    </script>

    <div class="dashboard-container">
        <!-- Header Section -->
        <header class="top-bar">
            <div class="title-section">
                <img src="logo-goodyear.png" alt="Goodyear Logo" class="logo">
                <div>
                    <h1>STATUS ASRS</h1>
                    <span class="subtitle">Mecatronico1 + mecatrónico2 + Coordinador</span>
                </div>
            </div>
            <div class="time-section">
                <div class="datetime">Fecha/Hora: <span id="clock" class="highlight-text">FECHA@HORA</span></div>
            </div>
            <div class="source-section text-right text-muted">
                <small>Desde base de datos interna</small>
                <button id="theme-toggle" class="theme-toggle-btn" aria-label="Cambiar tema">
                    <svg id="theme-icon" xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-sun"><circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/></svg>
                </button>
            </div>
        </header>

        <!-- Controls Bar for Time Filtering -->
        <section class="controls-bar">
            <div class="filter-group">
                <label class="switch-container">
                    <input type="checkbox" id="live-checkbox" checked>
                    <span class="switch-slider"></span>
                </label>
                <span class="filter-label" id="live-label">En Vivo 🟢</span>
            </div>
            
            <div class="range-inputs">
                <div class="input-field">
                    <label for="start-time">Inicio:</label>
                    <input type="datetime-local" id="start-time" disabled>
                </div>
                <div class="input-field">
                    <label for="end-time">Fin:</label>
                    <input type="datetime-local" id="end-time" disabled>
                </div>
                <button id="btn-query" class="btn-primary" disabled>Consultar</button>
            </div>
        </section>

        <!-- Main Grid Layout -->
        <main class="grid-layout">
            
            <!-- CONVEYOR FULL -->
            <section class="card">
                <div class="card-header">
                    <div class="card-title">
                        <span class="indicator green"></span>
                        <h2>CONVEYOR FULL</h2>
                        <span class="kpi-bracket">[Total = <span class="highlight">XXXX</span> min - Objetivo: <span class="highlight">YYYYY</span> m]</span>
                    </div>
                    <div class="card-source text-muted"><small>Datos provienen APS de TBM</small></div>
                </div>
                <div class="card-content flex-row">
                    <div class="data-group">
                        <span class="label">Lado Pared</span>
                        <span class="value">ZZZZZ m</span>
                    </div>
                    <div class="data-group">
                        <span class="label">Lado Pasillo</span>
                        <span class="value">WWWW m</span>
                    </div>
                </div>
            </section>

            <!-- PLUMMERS -->
            <section class="card">
                <div class="card-header">
                    <div class="card-title">
                        <span class="indicator green"></span>
                        <h2>PLUMMERS</h2>
                        <span class="kpi-bracket">[Total = <span class="highlight">XXXX</span> tires - Objetivo: <span class="highlight">YYYYY</span> tires]</span>
                    </div>
                    <div class="card-source text-muted"><small>Datos desde PLC de cada plummer</small></div>
                </div>
                <div class="card-content">
                    <table class="data-table">
                        <thead>
                            <tr>
                                <th></th>
                                <th>Idle [m]</th>
                                <th>Working [m]</th>
                                <th>Waiting [m]</th>
                                <th>Clean [m]</th>
                                <th># Tires</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr>
                                <td>Lubricadora 1</td>
                                <td>-</td><td>-</td><td>-</td><td>-</td><td>-</td>
                            </tr>
                            <tr>
                                <td>Lubricadora 2</td>
                                <td>-</td><td>-</td><td>-</td><td>-</td><td>-</td>
                            </tr>
                            <tr>
                                <td>Lubricadora 3</td>
                                <td>-</td><td>-</td><td>-</td><td>-</td><td>-</td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </section>

            <!-- ROBOTS -->
            <section class="card">
                <div class="card-header">
                    <div class="card-title">
                        <span class="indicator green"></span>
                        <h2>Robots</h2>
                    </div>
                    <div class="card-source text-muted"><small>Datos desde PLC de cada robot</small></div>
                </div>
                <div class="card-content">
                    <table class="data-table">
                        <thead>
                            <tr>
                                <th></th>
                                <th>Idle</th>
                                <th>Working</th>
                                <th>Waiting</th>
                                <th>Failure</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr>
                                <td>RL1</td>
                                <td>AAA</td><td>BBB</td><td>CCCC</td><td>DDD</td>
                            </tr>
                            <tr>
                                <td>RL2</td>
                                <td>AAAA</td><td>-</td><td>-</td><td>-</td>
                            </tr>
                            <tr>
                                <td>RU1</td>
                                <td>AA</td><td>-</td><td>-</td><td>-</td>
                            </tr>
                            <tr>
                                <td>RU2</td>
                                <td>-</td><td>-</td><td>-</td><td>-</td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </section>

            <!-- DOWNTIME CONVEYOR -->
            <section class="card">
                <div class="card-header">
                    <div class="card-title">
                        <span class="indicator green"></span>
                        <h2>DOWNTIME CONVEYOR</h2>
                        <span class="kpi-bracket">[Recirculación= <span class="highlight">XXXX</span> tires]</span>
                    </div>
                    <div class="card-source text-muted"><small>Datos desde cada PLC</small></div>
                </div>
                <div class="card-content flex-row">
                    <div class="data-group">
                        <span class="label">CC01=</span>
                        <span class="value">m</span>
                    </div>
                    <div class="data-group">
                        <span class="label">CC02=</span>
                        <span class="value">m</span>
                    </div>
                    <div class="data-group">
                        <span class="label">CC03=</span>
                        <span class="value">m</span>
                    </div>
                </div>
            </section>

            <!-- NO TIRE -->
            <section class="card">
                <div class="card-header">
                    <div class="card-title">
                        <span class="indicator green"></span>
                        <h2>NO TIRE</h2>
                        <span class="kpi-bracket">[Total = <span class="highlight" id="no-tire-total-percent">-</span> % (<span id="no-tire-total-min">-</span> min) - Objetivo: <span class="highlight">0.50</span> %]</span>
                    </div>
                    <div class="card-source text-muted"><small>Datos desde APS de Vulca y SBS</small></div>
                </div>
                <div class="card-content">
                    <div class="grid-table-no-tire">
                        <div class="grid-header">100A</div>
                        <div class="grid-header">100B</div>
                        <div class="grid-header">200A</div>
                        <div class="grid-header">200B</div>
                        <div class="grid-header">300A</div>
                        <div class="grid-header">300B</div>
                        <div class="grid-header">400A</div>
                        <div class="grid-header">400B</div>
                        <div class="grid-header">500A</div>
                        <div class="grid-header">500B</div>
                        <div class="grid-header">600A</div>
                        <div class="grid-header">600B</div>
                        
                        <div class="grid-cell" id="nt-100a">-</div>
                        <div class="grid-cell" id="nt-100b">-</div>
                        <div class="grid-cell" id="nt-200a">-</div>
                        <div class="grid-cell" id="nt-200b">-</div>
                        <div class="grid-cell" id="nt-300a">-</div>
                        <div class="grid-cell" id="nt-300b">-</div>
                        <div class="grid-cell" id="nt-400a">-</div>
                        <div class="grid-cell" id="nt-400b">-</div>
                        <div class="grid-cell" id="nt-500a">-</div>
                        <div class="grid-cell" id="nt-500b">-</div>
                        <div class="grid-cell" id="nt-600a">-</div>
                        <div class="grid-cell" id="nt-600b">-</div>
                    </div>
                </div>
            </section>

            <!-- MANTENCIÓN PREVENTIVA ROBOT -->
            <section class="card">
                <div class="card-header">
                    <div class="card-title">
                        <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-key" style="vertical-align: middle; margin-right: 4px; color: var(--accent-color);"><circle cx="7.5" cy="15.5" r="5.5"/><path d="m21 2-9.6 9.6"/><path d="m15.5 7.5 3 3L21 8"/></svg>
                        <span class="indicator green"></span>
                        <h2>MANTENCIÓN PREVENTIVA ROBOT</h2>
                        <span class="kpi-bracket">[Total = <span class="highlight" id="pm-total-percent">-</span> % (<span id="pm-total-min">-</span> min) - Objetivo: <span class="highlight">1.00</span> %]</span>
                    </div>
                    <div class="card-source text-muted"><small>Datos desde planificación de mantenimiento</small></div>
                </div>
                <div class="card-content">
                    <div class="grid-table-12">
                        <div class="grid-header">100A</div>
                        <div class="grid-header">100B</div>
                        <div class="grid-header">200A</div>
                        <div class="grid-header">200B</div>
                        <div class="grid-header">300A</div>
                        <div class="grid-header">300B</div>
                        <div class="grid-header">400A</div>
                        <div class="grid-header">400B</div>
                        <div class="grid-header">500A</div>
                        <div class="grid-header">500B</div>
                        <div class="grid-header">600A</div>
                        <div class="grid-header">600B</div>
                        
                        <div class="grid-cell" id="pm-100a">-</div>
                        <div class="grid-cell" id="pm-100b">-</div>
                        <div class="grid-cell" id="pm-200a">-</div>
                        <div class="grid-cell" id="pm-200b">-</div>
                        <div class="grid-cell" id="pm-300a">-</div>
                        <div class="grid-cell" id="pm-300b">-</div>
                        <div class="grid-cell" id="pm-400a">-</div>
                        <div class="grid-cell" id="pm-400b">-</div>
                        <div class="grid-cell" id="pm-500a">-</div>
                        <div class="grid-cell" id="pm-500b">-</div>
                        <div class="grid-cell" id="pm-600a">-</div>
                        <div class="grid-cell" id="pm-600b">-</div>
                    </div>
                </div>
            </section>

            <!-- MANTENCIÓN PREVENTIVA GENERAL -->
            <section class="card">
                <div class="card-header">
                    <div class="card-title">
                        <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-settings" style="vertical-align: middle; margin-right: 4px; color: var(--accent-color);"><path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.1a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/></svg>
                        <span class="indicator green"></span>
                        <h2>MANTENCIÓN PREVENTIVA GENERAL</h2>
                        <span class="kpi-bracket">[Total = <span class="highlight" id="pmg-total-percent">-</span> % (<span id="pmg-total-min">-</span> min) - Objetivo: <span class="highlight">1.00</span> %]</span>
                    </div>
                    <div class="card-source text-muted"><small>Datos desde planificación de mantenimiento</small></div>
                </div>
                <div class="card-content">
                    <div class="grid-table-12">
                        <div class="grid-header">100A</div>
                        <div class="grid-header">100B</div>
                        <div class="grid-header">200A</div>
                        <div class="grid-header">200B</div>
                        <div class="grid-header">300A</div>
                        <div class="grid-header">300B</div>
                        <div class="grid-header">400A</div>
                        <div class="grid-header">400B</div>
                        <div class="grid-header">500A</div>
                        <div class="grid-header">500B</div>
                        <div class="grid-header">600A</div>
                        <div class="grid-header">600B</div>
                        
                        <div class="grid-cell" id="pmg-100a">-</div>
                        <div class="grid-cell" id="pmg-100b">-</div>
                        <div class="grid-cell" id="pmg-200a">-</div>
                        <div class="grid-cell" id="pmg-200b">-</div>
                        <div class="grid-cell" id="pmg-300a">-</div>
                        <div class="grid-cell" id="pmg-300b">-</div>
                        <div class="grid-cell" id="pmg-400a">-</div>
                        <div class="grid-cell" id="pmg-400b">-</div>
                        <div class="grid-cell" id="pmg-500a">-</div>
                        <div class="grid-cell" id="pmg-500b">-</div>
                        <div class="grid-cell" id="pmg-600a">-</div>
                        <div class="grid-cell" id="pmg-600b">-</div>
                    </div>
                </div>
            </section>

            <!-- INPUT / OUTPUT -->
            <section class="card">
                <div class="card-header">
                    <div class="card-title">
                        <span class="indicator green"></span>
                        <h2>INPUT / OUTPUT</h2>
                        <span class="kpi-bracket">[Eficiencia Entrada= <span class="highlight">XXXXX</span> % - Objetivo: <span class="highlight">YYYYY</span> %]</span>
                    </div>
                    <div class="card-source text-muted"><small>Datos APS - TBM</small></div>
                </div>
                <div class="card-content">
                    <div class="stats-grid">
                        <div class="stat-box">
                            <span class="label">Entrada</span>
                            <span class="value" id="io-entrada-val">- <small>tires</small></span>
                            <span class="sub-value" id="io-entrada-rate">Rate= - <small>tires/m</small></span>
                        </div>
                        <div class="stat-box">
                            <span class="label">Manual</span>
                            <span class="value" id="io-manual-val">- <small>tires</small></span>
                            <span class="sub-value" id="io-manual-rate">Rate= - <small>tires/m</small></span>
                        </div>
                        <div class="stat-box">
                            <span class="label">Auto</span>
                            <span class="value" id="io-auto-val">- <small>tires</small></span>
                            <span class="sub-value" id="io-auto-rate">Rate= - <small>tires/m</small></span>
                        </div>
                    </div>
                </div>
            </section>

            <!-- CRANE PERFORMANCE -->
            <section class="card">
                <div class="card-header">
                    <div class="card-title">
                        <span class="indicator green"></span>
                        <h2>Crane performance</h2>
                        <span class="kpi-bracket">[Uptime = <span class="highlight">XXXXX</span> %]</span>
                    </div>
                </div>
                <div class="card-content flex-column">
                    <div class="data-group">
                        <span class="label">Top5 Downtime:</span>
                        <span class="value">CRX, CRJ, Cro, CRK</span>
                    </div>
                    <div class="data-group">
                        <span class="label">Top5 Minor Stop:</span>
                        <span class="value">CRY XX, CRh CC, Crpo NN, CRP NN</span>
                    </div>
                </div>
            </section>

            <!-- PRESS DELIVERY PERFORMANCE -->
            <section class="card">
                <div class="card-header">
                    <div class="card-title">
                        <span class="indicator green"></span>
                        <h2>PRESS DELIVERY PERFORMANCE</h2>
                        <span class="kpi-bracket">[Uptime = <span class="highlight">XXXXX</span> %]</span>
                    </div>
                    <div class="card-source text-muted"><small>Datos desde APS de Vulca y SBS - Despachado/Vulcanizados</small></div>
                </div>
                <div class="card-content">
                    <div class="press-delivery-grid">
                        <div class="press-item">
                            <div class="press-id highlight">400B</div>
                            <div class="press-stats">
                                <div class="despachados">Despachados: -</div>
                                <div class="vulcanizados">Vulcanizados: -</div>
                            </div>
                        </div>
                        <div class="press-item">
                            <div class="press-id highlight">500A</div>
                            <div class="press-stats">
                                <div class="despachados">Despachados: -</div>
                                <div class="vulcanizados">Vulcanizados: -</div>
                            </div>
                        </div>
                        <div class="press-item">
                            <div class="press-id highlight">500B</div>
                            <div class="press-stats">
                                <div class="despachados">Despachados: -</div>
                                <div class="vulcanizados">Vulcanizados: -</div>
                            </div>
                        </div>
                        <div class="press-item">
                            <div class="press-id highlight">600A</div>
                            <div class="press-stats">
                                <div class="despachados">Despachados: -</div>
                                <div class="vulcanizados">Vulcanizados: -</div>
                            </div>
                        </div>
                        <div class="press-item">
                            <div class="press-id highlight">600B</div>
                            <div class="press-stats">
                                <div class="despachados">Despachados: -</div>
                                <div class="vulcanizados">Vulcanizados: -</div>
                            </div>
                        </div>
                    </div>
                </div>
            </section>

        </main>
    </div>

    <script src="script.js?v=<?php echo time(); ?>"></script>
</body>
</html>
