
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
    const themeIcon = document.getElementById('theme-icon');
    
    const prefersDarkScheme = window.matchMedia("(prefers-color-scheme: dark)");
    const currentTheme = localStorage.getItem("theme");
    
    if (currentTheme == "light" || (!currentTheme && !prefersDarkScheme.matches)) {
        document.body.classList.add("light-mode");
        updateThemeIcon("light");
    } else {
        updateThemeIcon("dark");
    }

    themeToggleBtn.addEventListener("click", function() {
        document.body.classList.toggle("light-mode");
        let theme = "dark";
        if (document.body.classList.contains("light-mode")) {
            theme = "light";
        }
        localStorage.setItem("theme", theme);
        updateThemeIcon(theme);
    });

    function updateThemeIcon(theme) {
        if (theme === "light") {
            themeIcon.innerHTML = '<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/>';
        } else {
            themeIcon.innerHTML = '<circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/>';
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

    // Filter controls
    const startDateInput = document.getElementById('start-date');
    const startTimeInput = document.getElementById('start-time');
    const endDateInput = document.getElementById('end-date');
    const endTimeInput = document.getElementById('end-time');
    const btnQuery = document.getElementById('btn-query');

    // Restringir el calendario HTML al día de ayer como mínimo
    const now = new Date();
    const minDate = new Date(now.getTime() - 24 * 60 * 60 * 1000);
    const minDateString = minDate.toISOString().split('T')[0];
    if (startDateInput) startDateInput.setAttribute('min', minDateString);
    if (endDateInput) endDateInput.setAttribute('min', minDateString);

    function formatDate(date) {
        const yyyy = date.getFullYear();
        const mm = String(date.getMonth() + 1).padStart(2, '0');
        const dd = String(date.getDate()).padStart(2, '0');
        return `${yyyy}-${mm}-${dd}`;
    }

    function formatTime(date) {
        const hh = String(date.getHours()).padStart(2, '0');
        const min = String(date.getMinutes()).padStart(2, '0');
        return `${hh}:${min}`;
    }

    function setInputs(startDt, endDt) {
        startDateInput.value = formatDate(startDt);
        startTimeInput.value = formatTime(startDt);
        endDateInput.value = formatDate(endDt);
        endTimeInput.value = formatTime(endDt);
    }

    function getStartDateTime() {
        return `${startDateInput.value}T${startTimeInput.value}`;
    }

    function getEndDateTime() {
        return `${endDateInput.value}T${endTimeInput.value}`;
    }

    // Helper to get current shift interval up to now
    function getCurrentShiftInterval() {
        const now = new Date();
        const hour = now.getHours();
        let startDt;

        if (hour >= 6 && hour < 14) {
            startDt = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 6, 0, 0, 0);
        } else if (hour >= 14 && hour < 22) {
            startDt = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 14, 0, 0, 0);
        } else if (hour >= 22) {
            startDt = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 22, 0, 0, 0);
        } else {
            const yesterday = new Date(now.getTime() - 24 * 60 * 60 * 1000);
            startDt = new Date(yesterday.getFullYear(), yesterday.getMonth(), yesterday.getDate(), 22, 0, 0, 0);
        }
        return { startDt, endDt: now };
    }

    // Default to current shift up to now
    const initialInterval = getCurrentShiftInterval();
    setInputs(initialInterval.startDt, initialInterval.endDt);

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
        document.getElementById('plummers-tbody').innerHTML = `
            <tr><td><strong>Lubricadora 1</strong></td><td>-</td><td>-</td><td>-</td></tr>
            <tr><td><strong>Lubricadora 2</strong></td><td>-</td><td>-</td><td>-</td></tr>
            <tr><td><strong>Lubricadora 3</strong></td><td>-</td><td>-</td><td>-</td></tr>
        `;
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
                            <span>Desp: <strong>-</strong></span>
                            <span>Vulc: <strong>-</strong></span>
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
        const convCard = document.getElementById('conv-tbody')?.closest('.card-content');
        const robotsCard = document.getElementById('robots-tbody')?.closest('.card-content');
        const msgHtml = `<div class="empty-state-msg">La información no está disponible por el momento</div>`;
        if (convCard) convCard.innerHTML = msgHtml;
        if (robotsCard) robotsCard.innerHTML = msgHtml;
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
                    setIndicatorColor('ind-press-delivery', data.uptime >= 98.00);

                    const container = document.getElementById('press-delivery-container');
                    let pressesHtml = '';
                    const order = ["400B", "500A", "500B", "600A", "600B"];
                    order.forEach(p => {
                        const stats = data.presses[p] || { delivered: 0, cancelled: 0, total: 0, vulcanized: 0 };
                        const valid = stats.delivered + stats.cancelled;
                        const compliance = valid > 0 ? (stats.delivered / valid * 100) : 100.0;
                        const complianceColor = compliance >= 98.0 ? 'var(--success-color)' : (compliance >= 95.0 ? 'var(--warning-color)' : 'var(--danger-color)');
                        pressesHtml += `
                            <div class="press-row-item">
                                <div class="press-row-header">
                                    <span class="press-row-id">${p}</span>
                                    <span class="press-row-pct" style="color: ${complianceColor};">${compliance.toFixed(1)}%</span>
                                </div>
                                <div class="press-progress-bar-bg">
                                    <div class="press-progress-bar-fill" style="width: ${compliance}%; background-color: ${complianceColor};"></div>
                                </div>
                                <div class="press-row-stats">
                                    <span>Desp: <strong>${stats.delivered}</strong></span>
                                    <span>Vulc: <strong>${stats.vulcanized || 0}</strong></span>
                                </div>
                            </div>
                        `;
                    });
                    
                    container.innerHTML = `
                        <div class="press-delivery-left">
                            <div class="press-overall-gauge">
                                <div class="press-overall-val">${data.uptime.toFixed(2)}%</div>
                                <div class="press-overall-label">Eficiencia de Despacho</div>
                            </div>
                        </div>
                        <div class="press-delivery-right">
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
        const plummersCard = document.getElementById('plummers-tbody')?.closest('.card-content');
        const msgHtml = `<div class="empty-state-msg">La información no está disponible por el momento</div>`;
        if (plummersCard) plummersCard.innerHTML = msgHtml;
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

    function fetchAllData() {
        fetchDailyTicket();
        fetchInputOutputData(getStartDateTime(), getEndDateTime());
        fetchConveyorFullData(getStartDateTime(), getEndDateTime());
        fetchPLCConveyorData(getStartDateTime(), getEndDateTime());
        fetchCranePerformanceData();
        fetchAsrsEngineeringData();
        fetchPressDeliveryData();

        
        const startVal = getStartDateTime();
        const endVal = getEndDateTime();
        
        // 160000 = No Tire, 210002 = PM Robot
        // Se suman ambos motivos en la misma tarjeta "NO TIRE"
        fetchDowntimeData('160000,210002', startVal, endVal, 'no-tire-total-percent', 'no-tire-total-min', 'nt', 'ind-no-tire', 0.50);
    }


    btnQuery.addEventListener('click', () => {
        if (!startDateInput.value || !startTimeInput.value || !endDateInput.value || !endTimeInput.value) {
            alert('Por favor seleccione fecha y hora de inicio y fin.');
            return;
        }

        const startDt = new Date(getStartDateTime());
        const endDt = new Date(getEndDateTime());
        const now = new Date();

        // Validar que la fecha de inicio no sea mayor a la de fin
        if (startDt > endDt) {
            alert('La fecha de inicio no puede ser mayor a la fecha de fin.');
            return;
        }

        // Restringir el buscador a las últimas 24 horas (margen de 24.5h)
        const diffHoursPast = (now - startDt) / (1000 * 60 * 60);
        if (diffHoursPast > 24.5) {
            alert('La información disponible está restringida a las últimas 24 horas. Por favor seleccione una fecha y hora de inicio más reciente.');
            return;
        }

        fetchAllData();
    });

    function getSelectedBaseDate() {
        let baseVal = endDateInput.value;
        if (!baseVal) {
            baseVal = startDateInput.value;
        }
        if (!baseVal) {
            baseVal = formatDate(new Date());
        }
        return baseVal;
    }

    function getPresetShiftDates(startHour) {
        const now = new Date();
        // Siempre usar el día de hoy como base para los presets rápidos de turno
        let startDt = new Date(now.getFullYear(), now.getMonth(), now.getDate(), startHour, 0, 0);
        
        // Si la hora de inicio del turno es en el futuro, retrocedemos 24 horas (al día anterior)
        if (startDt > now) {
            startDt = new Date(startDt.getTime() - 24 * 60 * 60 * 1000);
        }
        
        let endDt = new Date(startDt.getTime() + 8 * 60 * 60 * 1000);
        // Si la hora de término del turno es en el futuro, la limitamos al momento actual (para no consultar el futuro)
        if (endDt > now) {
            endDt = now;
        }
        return { startDt, endDt };
    }

    // Program presets
    document.getElementById('preset-turn-day').addEventListener('click', () => {
        const { startDt, endDt } = getPresetShiftDates(6);
        setInputs(startDt, endDt);
        fetchAllData();
    });

    document.getElementById('preset-turn-afternoon').addEventListener('click', () => {
        const { startDt, endDt } = getPresetShiftDates(14);
        setInputs(startDt, endDt);
        fetchAllData();
    });

    document.getElementById('preset-turn-night').addEventListener('click', () => {
        const { startDt, endDt } = getPresetShiftDates(22);
        setInputs(startDt, endDt);
        fetchAllData();
    });

    document.getElementById('preset-last-8').addEventListener('click', () => {
        const endDt = new Date();
        const startDt = new Date(endDt.getTime() - 8 * 60 * 60 * 1000);
        setInputs(startDt, endDt);
        fetchAllData();
    });

    document.getElementById('preset-last-24').addEventListener('click', () => {
        const endDt = new Date();
        const startDt = new Date(endDt.getTime() - 24 * 60 * 60 * 1000);
        setInputs(startDt, endDt);
        fetchAllData();
    });

    // Initial triggers
    initStaticWidgets();
    fetchAllData();

});
