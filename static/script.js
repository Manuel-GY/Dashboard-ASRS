
async function fetchWithRetry(url, options = {}, retries = 2, backoff = 1000) {
    for (let i = 0; i <= retries; i++) {
        try {
            const response = await fetch(url, options);
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            return response;
        } catch (error) {
            if (i === retries) throw error;
            console.warn(`Fetch error for ${url}. Retrying in ${backoff}ms (${i + 1}/${retries})...`);
            await new Promise(resolve => setTimeout(resolve, backoff));
        }
    }
}
document.addEventListener('DOMContentLoaded', () => {
    // Clock functionality
    const clockElement = document.getElementById('clock');
    
    function updateClock() {
        const now = new Date();
        
        const day = String(now.getDate()).padStart(2, '0');
        const month = String(now.getMonth() + 1).padStart(2, '0');
        const year = now.getFullYear();
        const date = `${day}/${month}/${year}`;
        
        const time = now.toLocaleTimeString('es-CL', {
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit'
        });
        
        clockElement.textContent = `${date} @ ${time}`;
    }

    updateClock();
    setInterval(updateClock, 1000);

    // Theme toggle functionality
    const themeToggleBtn = document.getElementById('theme-toggle');
    const iconSun = document.getElementById('theme-icon-sun');
    const iconMoon = document.getElementById('theme-icon-moon');
    
    const prefersDarkScheme = window.matchMedia("(prefers-color-scheme: dark)");
    const currentTheme = localStorage.getItem("theme");
    
    if (currentTheme == "light" || (!currentTheme && !prefersDarkScheme.matches)) {
        document.body.classList.add("light-mode");
        updateThemeIcon("light");
    } else {
        document.body.classList.remove("light-mode");
        updateThemeIcon("dark");
    }

    if (themeToggleBtn) {
        themeToggleBtn.addEventListener("click", function(e) {
            e.preventDefault();
            alert("¡Clic detectado por el botón!");
            document.body.classList.toggle("light-mode");
            let theme = "dark";
            if (document.body.classList.contains("light-mode")) {
                theme = "light";
            }
            localStorage.setItem("theme", theme);
            updateThemeIcon(theme);
        });
    }

    function updateThemeIcon(theme) {
        if (iconSun && iconMoon) {
            if (theme === "light") {
                iconSun.style.display = 'none';
                iconMoon.style.display = 'block';
            } else {
                iconSun.style.display = 'block';
                iconMoon.style.display = 'none';
            }
        }
    }

    // Input/Output Data
    function fetchInputOutputData(start = '', end = '') {
        let url = '/api/io-data';
        if (start && end) {
            url += `?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`;
        }
        fetchWithRetry(url)
            .then(response => response.json())
            .then(data => {
                document.getElementById('io-entrada-val').innerHTML = `${data.entrada} <small>tires</small>`;
                document.getElementById('io-entrada-rate').innerHTML = `Rate= ${data.rate_entrada} <small>tires/m</small>`;
                
                document.getElementById('io-manual-val').innerHTML = `${data.manual} <small>tires</small>`;
                document.getElementById('io-manual-rate').innerHTML = `Rate= ${data.rate_manual} <small>tires/m</small>`;
                
                document.getElementById('io-auto-val').innerHTML = `${data.auto} <small>tires</small>`;
                document.getElementById('io-auto-rate').innerHTML = `Rate= ${data.rate_auto} <small>tires/m</small>`;

                // Calculamos eficiencia aproximada
                const totalOut = parseFloat(data.manual) + parseFloat(data.auto);
                const totalIn = parseFloat(data.entrada);
                let efficiency = null;
                if (!isNaN(totalIn) && !isNaN(totalOut) && totalIn > 0) {
                    efficiency = (totalOut / totalIn) * 100;
                }
                const effEl = document.getElementById('io-efficiency');
                if (effEl) {
                    if (efficiency !== null) {
                        effEl.textContent = efficiency.toFixed(2);
                        setIndicatorColor('ind-io', efficiency >= 95.0);
                    } else {
                        effEl.textContent = '-';
                        setIndicatorColor('ind-io', null);
                    }
                }
                const msgEl = document.getElementById('io-message');
                if (msgEl) {
                    if (data.message) {
                        msgEl.textContent = data.message;
                        msgEl.style.display = 'block';
                    } else {
                        msgEl.style.display = 'none';
                    }
                }
            })
            .catch(error => {
                console.error('Error fetching IO data:', error);
                setIndicatorColor('ind-io', false);
            });
    }

    // ============================================================================
    // GESTIÓN DE FECHAS, HORAS Y TURNOS
    // ============================================================================
    
    // Variables globales para almacenar el rango de tiempo actualmente seleccionado
    let currentStartDt = null;
    let currentEndDt = null;

    /**
     * Convierte un objeto Date al formato ISO-like requerido por la API del backend (YYYY-MM-DDTHH:MM)
     */
    function formatDateForApi(date) {
        if (!date) return '';
        const yyyy = date.getFullYear();
        const mm = String(date.getMonth() + 1).padStart(2, '0');
        const dd = String(date.getDate()).padStart(2, '0');
        const hh = String(date.getHours()).padStart(2, '0');
        const min = String(date.getMinutes()).padStart(2, '0');
        return `${yyyy}-${mm}-${dd}T${hh}:${min}`;
    }

    function getStartDateTime() {
        return formatDateForApi(currentStartDt);
    }

    function getEndDateTime() {
        return formatDateForApi(currentEndDt);
    }

    /**
     * Función principal de control de turnos.
     * Recibe un 'offset' (0 = Actual, 1 = Anterior, 2 = Hace 2 turnos, etc.)
     * y calcula dinámicamente las fechas de inicio y fin de ese turno basado en 
     * los horarios estándar de planta (06:00, 14:00, 22:00).
     */
    function setShiftInterval(offset) {
        const now = new Date();
        const hour = now.getHours();
        let currentShiftStartHour;

        if (hour >= 6 && hour < 14) {
            currentShiftStartHour = 6;
        } else if (hour >= 14 && hour < 22) {
            currentShiftStartHour = 14;
        } else {
            currentShiftStartHour = 22;
        }

        let startDt = new Date(now.getFullYear(), now.getMonth(), now.getDate(), currentShiftStartHour, 0, 0, 0);
        
        // Adjust for night shift (22:00) that started yesterday
        if (currentShiftStartHour === 22 && hour < 6) {
            startDt.setDate(startDt.getDate() - 1);
        }

        // Apply offset (each offset is -8 hours)
        if (offset > 0) {
            startDt.setHours(startDt.getHours() - (8 * offset));
        }

        let endDt = new Date(startDt);
        endDt.setHours(endDt.getHours() + 8);

        // Don't query the future
        if (offset === 0 && endDt > now) {
            endDt = now;
        }

        currentStartDt = startDt;
        currentEndDt = endDt;
        
        // Update label text
        const label = document.getElementById('shift-label-display');
        if (label) {
            let shiftName = '';
            const stH = startDt.getHours();
            if (stH === 6) shiftName = 'Día';
            else if (stH === 14) shiftName = 'Tarde';
            else shiftName = 'Noche';
            
            const dayStr = String(startDt.getDate()).padStart(2, '0') + '/' + String(startDt.getMonth() + 1).padStart(2, '0');
            
            if (offset === 0) label.textContent = `Turno Actual (${shiftName} ${dayStr})`;
            else if (offset === 1) label.textContent = `Turno Anterior (${shiftName} ${dayStr})`;
            else label.textContent = `Hace ${offset} Turnos (${shiftName} ${dayStr})`;
        }
    }

    // Default to current shift up to now
    setShiftInterval(0);

    // Helper: color status indicator based on objective
    function setIndicatorColor(indicatorId, isHealthy) {
        const el = document.getElementById(indicatorId);
        if (el) {
            el.removeAttribute('style'); // reset custom styles
            if (isHealthy === true) {
                el.className = 'indicator green';
                el.style.color = 'var(--success-color)';
                el.style.backgroundColor = 'var(--success-color)';
            } else if (isHealthy === false) {
                el.className = 'indicator red';
                el.style.color = 'var(--danger-color)';
                el.style.backgroundColor = 'var(--danger-color)';
            } else {
                el.className = 'indicator gray';
                el.style.color = 'var(--text-muted)';
                el.style.backgroundColor = 'var(--text-muted)';
            }
        }
    }

    function fetchDowntimeData(reason, start = '', end = '', percentId, minId, cellPrefix, indicatorId, targetLimit) {
        let url = `/api/downtime?reason=${reason}`;
        if (start && end) {
            url += `&start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`;
        }
        
        const percentEl = document.getElementById(percentId);
        const minEl = document.getElementById(minId);
        if (percentEl) percentEl.textContent = '...';
        if (minEl) minEl.textContent = '...';
        
        fetchWithRetry(url)
            .then(response => {
                if (!response.ok) throw new Error('API Response not OK');
                return response.json();
            })
            .then(data => {
                if (data.success) {
                    const pEl = document.getElementById(percentId);
                    const mEl = document.getElementById(minId);
                    if (pEl) pEl.textContent = data.downtime_percent.toFixed(2);
                    if (mEl) mEl.textContent = data.total_downtime.toFixed(2);
                    
                    // Actualizar indicadores visuales
                    setIndicatorColor(indicatorId, data.downtime_percent <= targetLimit);
                    

                    const groups = ['100A', '100B', '200A', '200B', '300A', '300B', '400A', '400B', '500A', '500B', '600A', '600B'];
                    const gridEl = document.getElementById(`${cellPrefix}-grid`);
                    if (gridEl) {
                        gridEl.innerHTML = ''; // clear previous
                        let hasData = false;
                        
                        groups.forEach(g => {
                            const val = (data && data.downtime_by_group && data.downtime_by_group[g] !== undefined) ? data.downtime_by_group[g] : 0;
                            // Threshold: > 1 min for PM/PMG. For No Tire (cellPrefix === 'nt'), show > 0 min as well? 
                            // User said: "las de 0 no mostrar... si estan todos en cero mostrar un texto" 
                            // I will use val > 1 for all just to be consistent, or val > 0 for No tire?
                            // Let's use val >= 1.0 (or val > 1.0, user said ">1 minuto")
                            const threshold = (cellPrefix === 'nt') ? 0 : 1.0; 
                            if (val > threshold) {
                                hasData = true;
                                gridEl.innerHTML += `
                                    <div class="downtime-group-box">
                                        <div class="group-name">${g}</div>
                                        <div class="group-val" style="color: var(--danger-color);">${val.toFixed(2)}m</div>
                                    </div>
                                `;
                            }
                        });

                        if (!hasData) {
                            let msg = "Sin tiempo perdido registrado (> 1 min).";
                            if (cellPrefix === 'nt') msg = "Sin tiempo perdido por No Tire.";
                            gridEl.innerHTML = `<div class="downtime-empty-msg">${msg}</div>`;
                        }
                    }
                }
            })
            .catch(error => {
                console.error(`Error fetching downtime code ${reason}:`, error);
                const pEl = document.getElementById(percentId);
                const mEl = document.getElementById(minId);
                if (pEl) pEl.textContent = 'Error';
                if (mEl) mEl.textContent = 'Error';
                setIndicatorColor(indicatorId, false);
            });
    }

    // Initialize static widgets that do not have active API endpoints
    function initStaticWidgets() {
        // 1. Conveyor Full — ahora con datos reales vía API
        document.getElementById('conv-total-display').textContent = '- min';
        setIndicatorColor('ind-conveyor-full', null);

        // 2. Plummers
        document.getElementById('plummers-total-tires').textContent = '-';
        setIndicatorColor('ind-plummers', null);

        // 3. Robots Performance
        // 3. Robots Performance
        ['lr1', 'lr2', 'ulr1', 'ulr2'].forEach(m => {
            const eRun = document.getElementById(`${m}-run`);
            const eIdle = document.getElementById(`${m}-idle`);
            const eStop = document.getElementById(`${m}-stop`);
            if (eRun) eRun.textContent = '-';
            if (eIdle) eIdle.textContent = '-';
            if (eStop) eStop.textContent = '-';
        });
        setIndicatorColor('ind-robots', null);

        // 4. Downtime Conveyor
        ['cc01', 'cc02', 'cc03'].forEach(m => {
            const eRun = document.getElementById(`${m}-run`);
            const eIdle = document.getElementById(`${m}-idle`);
            const eStop = document.getElementById(`${m}-stop`);
            if (eRun) eRun.textContent = '-';
            if (eIdle) eIdle.textContent = '-';
            if (eStop) eStop.textContent = '-';
        });
        setIndicatorColor('ind-downtime-conveyor', null);

        // 4.5 CC02 Turnos
        const eRun = document.getElementById('cc02-run');
        const eIdle = document.getElementById('cc02-idle');
        const eStop = document.getElementById('cc02-stop');
        if (eRun) eRun.textContent = '-';
        if (eIdle) eIdle.textContent = '-';
        if (eStop) eStop.textContent = '-';

        // 5. Crane Performance
        document.getElementById('crane-uptime').textContent = '-';
        const craneEmptyRow = `<tr><td colspan="2" style="text-align:center; color:var(--text-muted);">-</td></tr>`;
        const tbodyDt = document.querySelector('#crane-top-downtime tbody');
        const tbodyMn = document.querySelector('#crane-top-minor tbody');
        if (tbodyDt) tbodyDt.innerHTML = craneEmptyRow;
        if (tbodyMn) tbodyMn.innerHTML = craneEmptyRow;
        setIndicatorColor('ind-crane', null);

        // 6. Press Delivery Performance
        document.getElementById('press-delivery-container').innerHTML = `
            <div class="press-delivery-left">
                <div class="press-overall-gauge">
                    <div class="press-overall-val">- %</div>
                    <div class="press-overall-label">Eficiencia de Despacho</div>
                </div>
            </div>
            <div class="press-delivery-right">
                ${["400B", "500A", "500B", "600A", "600B"].map(p => `
                    <div class="press-row-item">
                        <div class="press-row-header">
                            <span class="press-row-id">${p}</span>
                            <span class="press-row-pct">-</span>
                        </div>
                        <div class="press-progress-bar-bg">
                            <div class="press-progress-bar-fill" style="width: 0%;"></div>
                        </div>
                        <div class="press-row-stats">
                            <span>Despacho robots: <strong>-</strong></span>
                            <span>Carga manual: <strong>-</strong></span>
                            <span>Vulcanizados total: <strong>-</strong></span>
                        </div>
                    </div>
                `).join('')}
            </div>
        `;
        setIndicatorColor('ind-press-delivery', null);
    }

    function fetchConveyorFullData(start = '', end = '') {
        let url = '/api/conveyor-full';
        if (start && end) {
            url += `?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`;
        }
        document.getElementById('conv-total-display').textContent = '... min';
        setIndicatorColor('ind-conveyor-full', null);

        fetchWithRetry(url)
            .then(response => {
                if (!response.ok) throw new Error('API Response not OK');
                return response.json();
            })
            .then(data => {
                if (data.success) {
                    const total = data.total_downtime;
                    document.getElementById('conv-total-display').textContent = `${total.toFixed(2)} min`;
                    setIndicatorColor('ind-conveyor-full', data.is_ok);
                } else {
                    document.getElementById('conv-total-display').textContent = 'Error';
                    setIndicatorColor('ind-conveyor-full', false);
                }
            })
            .catch(error => {
                console.error('Error fetching Conveyor Full data:', error);
                document.getElementById('conv-total-display').textContent = 'Error';
                setIndicatorColor('ind-conveyor-full', false);
            });
    }

    function fetchPLCConveyorData(start = '', end = '') {
        let url = '/api/plc-conveyor';
        if (start && end) {
            url += `?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`;
        }
        
        ['cc01', 'cc02', 'cc03'].forEach(m => {
            if (document.getElementById(`${m}-run`)) document.getElementById(`${m}-run`).textContent = '...';
            if (document.getElementById(`${m}-idle`)) document.getElementById(`${m}-idle`).textContent = '...';
            if (document.getElementById(`${m}-stop`)) document.getElementById(`${m}-stop`).textContent = '...';
        });

        fetchWithRetry(url)
            .then(response => response.json())
            .then(data => {
                if (data.success && data.data) {
                    const machines = ['CC01', 'CC02', 'CC03'];
                    machines.forEach(m => {
                        const mId = m.toLowerCase();
                        if (data.data[m]) {
                            if (document.getElementById(`${mId}-run`)) document.getElementById(`${mId}-run`).textContent = data.data[m].RUN !== undefined ? data.data[m].RUN : '-';
                            if (document.getElementById(`${mId}-idle`)) document.getElementById(`${mId}-idle`).textContent = data.data[m].IDLE !== undefined ? data.data[m].IDLE : '-';
                            if (document.getElementById(`${mId}-stop`)) document.getElementById(`${mId}-stop`).textContent = data.data[m].STOP !== undefined ? data.data[m].STOP : '-';
                        }
                    });
                }
            })
            .catch(error => console.error('Error fetching PLC Conveyor data:', error));
            
        setIndicatorColor('ind-downtime-conveyor', null);
        setIndicatorColor('ind-robots', null);
    }


    function fetchCranePerformanceData() {
        const start = getStartDateTime();
        const end   = getEndDateTime();

        document.getElementById('crane-uptime').textContent = '...';
        const craneLoadingRow = `<tr><td colspan="2" style="text-align:center; color:var(--text-muted);">...</td></tr>`;
        const tbodyDtLoad = document.querySelector('#crane-top-downtime tbody');
        const tbodyMnLoad = document.querySelector('#crane-top-minor tbody');
        if (tbodyDtLoad) tbodyDtLoad.innerHTML = craneLoadingRow;
        if (tbodyMnLoad) tbodyMnLoad.innerHTML = craneLoadingRow;
        setIndicatorColor('ind-crane', null);

        let url = '/api/crane-performance';
        if (start && end) {
            url += `?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`;
        }

        fetchWithRetry(url)
            .then(response => {
                if (!response.ok) throw new Error('API Response not OK');
                return response.json();
            })
            .then(data => {
                if (!data.success) throw new Error('API returned failure');

                const aisles = data.data;
                if (!aisles || aisles.length === 0) {
                    document.getElementById('crane-uptime').textContent = '-';
                    document.getElementById('crane-top-downtime').textContent = 'Sin datos';
                    document.getElementById('crane-top-minor').textContent = 'Sin datos';
                    setIndicatorColor('ind-crane', null);
                    return;
                }

                // Calcular Uptime Promedio (100 - promedio de downtime)
                const totalDowntimePct = aisles.reduce((acc, curr) => acc + curr.downtime_percent, 0);
                const avgDowntimePct = totalDowntimePct / aisles.length;
                const uptimePct = 100 - avgDowntimePct;

                document.getElementById('crane-uptime').textContent = uptimePct.toFixed(2);
                setIndicatorColor('ind-crane', uptimePct >= 99.00);

                // Top5 Downtime: Los 5 Aisles con más minutos (mayor a 10)
                // Top5 Minor Stop: Los 5 Aisles con más minutos pero <= 10
                
                const sorted = [...aisles].sort((a, b) => b.downtime_minutes - a.downtime_minutes);

                const topDowntime = sorted.filter(a => a.downtime_minutes > 10).slice(0, 3);
                const topMinor = sorted.filter(a => a.downtime_minutes > 0 && a.downtime_minutes <= 10).slice(0, 3);

                // Función para generar filas de tabla HTML con barras visuales
                const formatAislesTable = (list, tbodyId) => {
                    const tbody = document.querySelector(`#${tbodyId} tbody`);
                    if (!tbody) return;
                    if (list.length === 0) {
                        tbody.innerHTML = `<tr><td colspan="2" style="text-align:center; color:var(--text-muted); font-style:italic;">Sin datos</td></tr>`;
                        return;
                    }
                    
                    const maxMins = Math.max(...list.map(a => a.downtime_minutes), 1);
                    
                    tbody.innerHTML = list.map(a => {
                        const pct = (a.downtime_minutes / maxMins) * 100;
                        return `
                        <tr>
                            <td style="font-weight:600; width:25%; padding:12px 8px; font-size:1.05rem;">Pasillo ${a.aisle}</td>
                            <td style="width:75%; padding:12px 8px;">
                                <div style="display:flex; align-items:center; gap:12px;">
                                    <div style="flex:1; background:var(--border-color); height:10px; border-radius:5px; overflow:hidden;">
                                        <div style="width:${pct}%; background:var(--danger-color); height:100%; border-radius:5px; transition:width 0.5s ease-out;"></div>
                                    </div>
                                    <span style="color:var(--danger-color); font-weight:700; font-size:1.1rem; width:55px; text-align:right;">${a.downtime_minutes}m</span>
                                </div>
                            </td>
                        </tr>
                        `;
                    }).join('');
                };

                // Si no hay > 10, mostramos los mayores en general que sean > 0
                const finalTopDowntime = topDowntime.length > 0 ? topDowntime : sorted.filter(a => a.downtime_minutes > 0).slice(0, 3);

                formatAislesTable(finalTopDowntime, 'crane-top-downtime');
                formatAislesTable(topMinor, 'crane-top-minor');
            })
            .catch(error => {
                console.error('Error fetching Crane Performance data:', error);
                document.getElementById('crane-uptime').textContent = 'Error';
                const errRow = `<tr><td colspan="2" style="text-align:center; color:var(--danger-color);">Error</td></tr>`;
                const tbodyDt = document.querySelector('#crane-top-downtime tbody');
                const tbodyMn = document.querySelector('#crane-top-minor tbody');
                if (tbodyDt) tbodyDt.innerHTML = errRow;
                if (tbodyMn) tbodyMn.innerHTML = errRow;
                setIndicatorColor('ind-crane', false);
            });
    }

    function fetchPressDeliveryData() {
        const start = getStartDateTime();
        const end   = getEndDateTime();

        setIndicatorColor('ind-press-delivery', null);

        let url = '/api/press-delivery';
        if (start && end) {
            url += `?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`;
        }

        fetchWithRetry(url)
            .then(response => {
                if (!response.ok) throw new Error('API Response not OK');
                return response.json();
            })
            .then(data => {
                if (data.success) {
                    const container = document.getElementById('press-delivery-container');
                    const overallVal = document.getElementById('press-overall-val');

                    let pressesHtml = '';
                    let globalDelivered = 0;
                    let globalVulcanized = 0;
                    const order = ["400B", "500A", "500B", "600A", "600B"];
                    
                    order.forEach(p => {
                        const stats = data.presses[p] || { delivered: 0, cancelled: 0, total: 0, vulcanized: 0 };
                        const t = stats.times || {idle: 0, estop: 0, cortinas: 0, prensa: 0, despachando: 0};
                        const totalTime = (t.idle + t.estop + t.cortinas + t.prensa + t.despachando) || 1;
                        
                        const idlePct = (t.idle / totalTime) * 100;
                        const estopPct = (t.estop / totalTime) * 100;
                        const cortinasPct = (t.cortinas / totalTime) * 100;
                        const prensaPct = (t.prensa / totalTime) * 100;
                        const despPct = (t.despachando / totalTime) * 100;

                        const vulcanized = stats.vulcanized || 0;
                        const delivered = stats.delivered || 0;
                        const manual = Math.max(0, vulcanized - delivered); // Prevent negative just in case
                        
                        globalDelivered += delivered;
                        globalVulcanized += vulcanized;

                        const compliance = vulcanized > 0 ? (delivered / vulcanized * 100) : 100.0;
                        const complianceColor = compliance >= 98.0 ? 'var(--success-color)' : (compliance >= 95.0 ? 'var(--warning-color)' : 'var(--danger-color)');

                        pressesHtml += `
                            <div class="press-row-item">
                                <div class="press-row-header">
                                    <span class="press-row-id">${p}</span>
                                    <span class="press-row-pct" style="color: ${complianceColor};">${compliance.toFixed(1)}%</span>
                                </div>
                                <div class="press-progress-bar-bg" style="display: flex;">
                                    <div title="Despachando: ${t.despachando.toFixed(0)}m" style="width: ${despPct}%; background-color: #84FF63; height: 100%;"></div>
                                    <div title="IDLE: ${t.idle.toFixed(0)}m" style="width: ${idlePct}%; background-color: #F3F30F; height: 100%;"></div>
                                    <div title="Cortinas: ${t.cortinas.toFixed(0)}m" style="width: ${cortinasPct}%; background-color: #49E2FF; height: 100%;"></div>
                                    <div title="Prensa: ${t.prensa.toFixed(0)}m" style="width: ${prensaPct}%; background-color: #C8783C; height: 100%;"></div>
                                    <div title="E-Stop: ${t.estop.toFixed(0)}m" style="width: ${estopPct}%; background-color: #FF0000; height: 100%;"></div>
                                </div>
                                <div class="press-row-stats" style="justify-content: space-between; display: flex;">
                                    <span>Despacho robots: <strong>${delivered}</strong></span>
                                    <span>Carga manual: <strong>${manual}</strong></span>
                                    <span>Vulcanizados total: <strong>${vulcanized}</strong></span>
                                </div>
                            </div>
                        `;
                    });
                    
                    const overallCompliance = globalVulcanized > 0 ? (globalDelivered / globalVulcanized * 100) : 100.0;
                    if (overallVal) {
                        overallVal.textContent = overallCompliance.toFixed(2) + '%';
                    }
                    setIndicatorColor('ind-press-delivery', overallCompliance >= 98.00);

                    container.innerHTML = `
                        <div class="press-delivery-right" style="width: 100%; border-left: none; padding-left: 0;">
                            ${pressesHtml}
                        </div>
                    `;
                } else {
                    throw new Error('API returned failure');
                }
            })
            .catch(error => {
                console.error('Error fetching Press Delivery data:', error);
                setIndicatorColor('ind-press-delivery', false);
            });
    }

    function fetchAsrsEngineeringData() {
        let url = '/api/asrs-engineering-data';
        const start = getStartDateTime();
        const end = getEndDateTime();
        if (start && end) {
            url += `?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`;
        }

        const plummersCard = document.getElementById('plummers-tbody')?.closest('.card-content');
        if (plummersCard && plummersCard.innerHTML.includes('La información no está disponible')) {
            plummersCard.innerHTML = `
                <table class="data-table">
                    <thead><tr><th></th><th>Run</th><th>Stop</th></tr></thead>
                    <tbody id="plummers-tbody">
                        <tr style="height: 33%;"><td style="padding: 15px 10px;">Lubricadora 1</td><td id="l1-run">...</td><td id="l1-idle">...</td><td id="l1-stop">...</td></tr>
                        <tr style="height: 33%;"><td style="padding: 15px 10px;">Lubricadora 2</td><td id="l2-run">...</td><td id="l2-idle">...</td><td id="l2-stop">...</td></tr>
                        <tr style="height: 33%;"><td style="padding: 15px 10px;">Lubricadora 3</td><td id="l3-run">...</td><td id="l3-idle">...</td><td id="l3-stop">...</td></tr>
                    </tbody>
                </table>`;
        }

        ['l1', 'l2', 'l3'].forEach(m => {
            if (document.getElementById(`${m}-run`)) document.getElementById(`${m}-run`).textContent = '...';
            if (document.getElementById(`${m}-idle`)) document.getElementById(`${m}-idle`).textContent = '...';
            if (document.getElementById(`${m}-stop`)) document.getElementById(`${m}-stop`).textContent = '...';
        });

        fetchWithRetry(url)
            .then(response => response.json())
            .then(data => {
                if (data.success && data.plummers) {
                    ['L1', 'L2', 'L3'].forEach(m => {
                        const mId = m.toLowerCase();
                        if (data.plummers[m]) {
                            if (document.getElementById(`${mId}-run`)) document.getElementById(`${mId}-run`).textContent = data.plummers[m].run !== undefined ? data.plummers[m].run : '-';
                            if (document.getElementById(`${mId}-idle`)) document.getElementById(`${mId}-idle`).textContent = data.plummers[m].idle !== undefined ? data.plummers[m].idle : '-';
                            if (document.getElementById(`${mId}-stop`)) document.getElementById(`${mId}-stop`).textContent = data.plummers[m].stop !== undefined ? data.plummers[m].stop : '-';
                        }
                    });

                    // Set last update label to DB timestamp
                    if (data.last_updated) {
                        const updateLbl = document.getElementById('last-update-label');
                        if (updateLbl) {
                            const parts = data.last_updated.split(' ');
                            if(parts.length === 2) {
                                const dateParts = parts[0].split('-');
                                const timeParts = parts[1].split(':');
                                if(dateParts.length === 3 && timeParts.length >= 2) {
                                    const dateStr = `${dateParts[2]}/${dateParts[1]}/${dateParts[0]}`;
                                    const timeStr = `${timeParts[0]}:${timeParts[1]}`;
                                    updateLbl.textContent = `Última actualización: ${dateStr} ${timeStr} (DB)`;
                                }
                            } else {
                                updateLbl.textContent = `Última actualización: ${data.last_updated}`;
                            }
                        }
                    }
                }
            })
            .catch(error => console.error('Error fetching ASRS Engineering data:', error));

        const totalTires = document.getElementById('plummers-total-tires');
        if (totalTires) totalTires.textContent = "-";
        setIndicatorColor('ind-plummers', null);
    }

    function fetchDailyTicket() {
        const ticketEl = document.getElementById('daily-ticket-val');
        if (!ticketEl) return;
        ticketEl.textContent = '...';
        
        fetchWithRetry('/api/daily-ticket')
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    ticketEl.textContent = `${data.formatted} tires`;
                } else {
                    ticketEl.textContent = 'N/D';
                }
            })
            .catch(error => {
                console.error('Error fetching daily ticket:', error);
                ticketEl.textContent = 'Error';
            });
    }



    function fetchLR1Turnos(start) {
        const eRun = document.getElementById('lr1-run');
        const eIdle = document.getElementById('lr1-idle');
        const eStop = document.getElementById('lr1-stop');
        if (eRun) eRun.textContent = '...';
        if (eIdle) eIdle.textContent = '...';
        if (eStop) eStop.textContent = '...';

        fetchWithRetry('/api/lr1-turnos')
            .then(response => response.json())
            .then(data => {
                if (data.success && data.data) {
                    let targetShift = 'T1';
                    if (start) {
                        const startDt = new Date(start);
                        const hour = startDt.getHours();
                        if (hour >= 6 && hour < 14) targetShift = 'T2';
                        else if (hour >= 14 && hour < 22) targetShift = 'T3';
                    }
                    if (eRun) eRun.textContent = data.data[targetShift].run;
                    if (eIdle) eIdle.textContent = data.data[targetShift].idle;
                    if (eStop) eStop.textContent = data.data[targetShift].fault;
                }
            })
            .catch(error => console.error('Error fetching LR1 turnos:', error));
    }

    function fetchLR2Turnos(start) {
        const eRun = document.getElementById('lr2-run');
        const eIdle = document.getElementById('lr2-idle');
        const eStop = document.getElementById('lr2-stop');
        if (eRun) eRun.textContent = '...';
        if (eIdle) eIdle.textContent = '...';
        if (eStop) eStop.textContent = '...';

        fetchWithRetry('/api/lr2-turnos')
            .then(response => response.json())
            .then(data => {
                if (data.success && data.data) {
                    let targetShift = 'T1';
                    if (start) {
                        const startDt = new Date(start);
                        const hour = startDt.getHours();
                        if (hour >= 6 && hour < 14) targetShift = 'T2';
                        else if (hour >= 14 && hour < 22) targetShift = 'T3';
                    }
                    if (eRun) eRun.textContent = data.data[targetShift].run;
                    if (eIdle) eIdle.textContent = data.data[targetShift].idle;
                    if (eStop) eStop.textContent = data.data[targetShift].fault;
                }
            })
            .catch(error => console.error('Error fetching LR2 turnos:', error));
    }

    function fetchULR1Turnos(start) {
        const eRun = document.getElementById('ulr1-run');
        const eIdle = document.getElementById('ulr1-idle');
        const eStop = document.getElementById('ulr1-stop');
        if (eRun) eRun.textContent = '...';
        if (eIdle) eIdle.textContent = '...';
        if (eStop) eStop.textContent = '...';

        fetchWithRetry('/api/ulr1-turnos')
            .then(response => response.json())
            .then(data => {
                if (data.success && data.data) {
                    let targetShift = 'T1'; // Noche por defecto
                    if (start) {
                        const startDt = new Date(start);
                        const hour = startDt.getHours();
                        if (hour >= 6 && hour < 14) {
                            targetShift = 'T2'; // Día
                        } else if (hour >= 14 && hour < 22) {
                            targetShift = 'T3'; // Tarde
                        }
                    }

                    if (eRun) eRun.textContent = data.data[targetShift].run;
                    if (eIdle) eIdle.textContent = data.data[targetShift].idle;
                    if (eStop) eStop.textContent = data.data[targetShift].fault;
                }
            })
            .catch(error => {
                console.error('Error fetching ULR1 turnos:', error);
            });
    }

    function fetchULR2Turnos(start) {
        const eRun = document.getElementById('ulr2-run');
        const eIdle = document.getElementById('ulr2-idle');
        const eStop = document.getElementById('ulr2-stop');
        if (eRun) eRun.textContent = '...';
        if (eIdle) eIdle.textContent = '...';
        if (eStop) eStop.textContent = '...';

        fetchWithRetry('/api/ulr2-turnos')
            .then(response => response.json())
            .then(data => {
                if (data.success && data.data) {
                    let targetShift = 'T1'; // Noche por defecto
                    if (start) {
                        const startDt = new Date(start);
                        const hour = startDt.getHours();
                        if (hour >= 6 && hour < 14) {
                            targetShift = 'T2'; // Día
                        } else if (hour >= 14 && hour < 22) {
                            targetShift = 'T3'; // Tarde
                        }
                    }

                    if (eRun) eRun.textContent = data.data[targetShift].run;
                    if (eIdle) eIdle.textContent = data.data[targetShift].idle;
                    if (eStop) eStop.textContent = data.data[targetShift].fault;
                }
            })
            .catch(error => {
                console.error('Error fetching ULR2 turnos:', error);
            });
    }

    function fetchAllData() {
        fetchDailyTicket();
        fetchInputOutputData(getStartDateTime(), getEndDateTime());
        fetchConveyorFullData(getStartDateTime(), getEndDateTime());
        fetchPLCConveyorData(getStartDateTime(), getEndDateTime());
        fetchLR1Turnos(getStartDateTime());
        fetchLR2Turnos(getStartDateTime());
        fetchULR1Turnos(getStartDateTime());
        fetchULR2Turnos(getStartDateTime());
        fetchCranePerformanceData();
        fetchAsrsEngineeringData();
        fetchPressDeliveryData();

        
        const startVal = getStartDateTime();
        const endVal = getEndDateTime();
        
        // 160000 = No Tire, 210002 = PM Robot
        // Se suman ambos motivos en la misma tarjeta "NO TIRE"
        fetchDowntimeData('160000,210002', startVal, endVal, 'no-tire-total-percent', 'no-tire-total-min', 'nt', 'ind-no-tire', 0.50);
    }


    function getSelectedBaseDate() {
        // Retorna solo la fecha (YYYY-MM-DD) del inicio del turno consultado, usado por APIs que agrupan por día
        if (!currentStartDt) return new Date().toISOString().split('T')[0];
        const yyyy = currentStartDt.getFullYear();
        const mm = String(currentStartDt.getMonth() + 1).padStart(2, '0');
        const dd = String(currentStartDt.getDate()).padStart(2, '0');
        return `${yyyy}-${mm}-${dd}`;
    }

    // ============================================================================
    // EVENT LISTENERS DE BOTONES DE TURNO
    // ============================================================================
    [0, 1, 2, 3].forEach(offset => {
        const btn = document.getElementById(`btn-shift-${offset}`);
        if (btn) {
            btn.addEventListener('click', () => {
                // Actualizar estado visual activo de los botones
                document.querySelectorAll('#shift-selector-buttons .btn-preset').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                
                // Calcular las nuevas fechas y recargar todos los datos del dashboard
                setShiftInterval(offset);
                fetchAllData();
            });
        }
    });

    // ============================================================================
    // PROGRAMADOR INTELIGENTE DE ACTUALIZACIONES (ENTREGA DE TURNO)
    // ============================================================================
    /**
     * Calcula los minutos restantes para la próxima extracción cron (horas pares a y 06 minutos)
     * (ej: 06:06, 08:06, 10:06) y agenda una recarga automática en el navegador.
     * Le da 1 minuto de ventaja sobre el backend (05 minutos) para garantizar que los datos estén listos.
     */
    function scheduleNextCronUpdate() {
        const now = new Date();
        const currentHour = now.getHours();
        const currentMinute = now.getMinutes();
        let nextUpdate = new Date(now);
        
        let targetHour = currentHour;
        // Si ya pasamos el minuto 6 o estamos en hora impar, avanzamos a la siguiente hora par
        if (currentHour % 2 !== 0 || (currentHour % 2 === 0 && currentMinute >= 6)) {
            targetHour = currentHour + (currentHour % 2 === 0 ? 2 : 1);
        }
        
        if (targetHour >= 24) {
            targetHour = 0;
            nextUpdate.setDate(nextUpdate.getDate() + 1);
        }
        
        nextUpdate.setHours(targetHour, 6, 0, 0);
        
        const timeUntilUpdate = nextUpdate - now;
        
        setTimeout(() => {
            // Actualizar estado del intervalo de fechas manteniendo el boton seleccionado
            let activeOffset = 0;
            document.querySelectorAll('#shift-selector-buttons .btn-preset').forEach((btn, idx) => {
                if (btn.classList.contains('active')) {
                    activeOffset = idx;
                }
            });
            setShiftInterval(activeOffset);
            fetchAllData();
            
            // Programar el siguiente ciclo recursivamente
            scheduleNextCronUpdate();
        }, timeUntilUpdate);
    }

    // Initial triggers
    initStaticWidgets();
    fetchAllData();
    
    // Iniciar el programador sincronizado con el cron del backend
    scheduleNextCronUpdate();

});
