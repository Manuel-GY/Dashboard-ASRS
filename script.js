document.addEventListener('DOMContentLoaded', () => {
    // Clock functionality
    const clockElement = document.getElementById('clock');
    
    function updateClock() {
        const now = new Date();
        
        const date = now.toLocaleDateString('es-CL', {
            year: 'numeric',
            month: '2-digit',
            day: '2-digit'
        });
        
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
    function fetchInputOutputData() {
        fetch('/api/io-data')
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
                let efficiency = 95.0;
                if (totalIn > 0) {
                    efficiency = (totalOut / totalIn) * 100;
                }
                const effEl = document.getElementById('io-efficiency');
                if (effEl) {
                    effEl.textContent = efficiency.toFixed(2);
                    setIndicatorColor('ind-io', efficiency >= 95.0);
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

    // Default to last 24 hours
    const now = new Date();
    const yesterday = new Date(now.getTime() - 24 * 60 * 60 * 1000);
    setInputs(yesterday, now);

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
        
        document.getElementById(percentId).textContent = '...';
        document.getElementById(minId).textContent = '...';
        
        fetch(url)
            .then(response => {
                if (!response.ok) throw new Error('API Response not OK');
                return response.json();
            })
            .then(data => {
                if (data.success) {
                    document.getElementById(percentId).textContent = data.downtime_percent.toFixed(2);
                    document.getElementById(minId).textContent = data.total_downtime.toFixed(2);
                    
                    // Actualizar indicadores visuales
                    setIndicatorColor(indicatorId, data.downtime_percent <= targetLimit);
                    

                    const groups = ['100A', '100B', '200A', '200B', '300A', '300B', '400A', '400B', '500A', '500B', '600A', '600B'];
                    const gridEl = document.getElementById(`${cellPrefix}-grid`);
                    if (gridEl) {
                        gridEl.innerHTML = ''; // clear previous
                        let hasData = false;
                        
                        groups.forEach(g => {
                            const val = data.downtime_by_group[g] !== undefined ? data.downtime_by_group[g] : 0;
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
                document.getElementById(percentId).textContent = 'Error';
                document.getElementById(minId).textContent = 'Error';
                setIndicatorColor(indicatorId, false);
            });
    }

    // Initialize static widgets that do not have active API endpoints
    function initStaticWidgets() {
        // 1. Conveyor Full — ahora con datos reales vía API
        document.getElementById('conv-total').textContent = '...';
        document.getElementById('conv-total-display').textContent = '- min';
        document.getElementById('conv-freq').textContent = '-';
        setIndicatorColor('ind-conveyor-full', null);

        // 2. Plummers
        document.getElementById('plummers-tbody').innerHTML = `
            <tr><td><strong>Lubricadora 1</strong></td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td></tr>
            <tr><td><strong>Lubricadora 2</strong></td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td></tr>
            <tr><td><strong>Lubricadora 3</strong></td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td></tr>
        `;
        document.getElementById('plummers-total-tires').textContent = '-';
        setIndicatorColor('ind-plummers', null);

        // 3. Robots Performance
        document.getElementById('robots-tbody').innerHTML = `
            <tr><td><strong>RL1</strong></td><td>-</td><td>-</td><td>-</td><td>-</td></tr>
            <tr><td><strong>RL2</strong></td><td>-</td><td>-</td><td>-</td><td>-</td></tr>
            <tr><td><strong>RU1</strong></td><td>-</td><td>-</td><td>-</td><td>-</td></tr>
            <tr><td><strong>RU2</strong></td><td>-</td><td>-</td><td>-</td><td>-</td></tr>
        `;
        setIndicatorColor('ind-robots', null);

        // 4. Downtime Conveyor
        document.getElementById('cc01-val').textContent = '-';
        document.getElementById('cc02-val').textContent = '-';
        document.getElementById('cc03-val').textContent = '-';
        document.getElementById('cc01-runtime').textContent = '-';
        document.getElementById('cc02-runtime').textContent = '-';
        document.getElementById('cc03-runtime').textContent = '-';
        setIndicatorColor('ind-cc01', null);
        setIndicatorColor('ind-cc02', null);
        setIndicatorColor('ind-cc03', null);
        setIndicatorColor('ind-downtime-conveyor', null);


        // 5. Crane Performance
        document.getElementById('crane-uptime').textContent = '-';
        document.getElementById('crane-top-downtime').textContent = 'No disponible';
        document.getElementById('crane-top-minor').textContent = 'No disponible';
        setIndicatorColor('ind-crane', null);

        // 6. Press Delivery Performance
        document.getElementById('press-delivery-uptime').textContent = '-';
        document.getElementById('press-delivery-container').innerHTML = `
            <div class="press-item"><div class="press-id highlight">400B</div><div class="press-stats"><div class="despachados">Despachados: -</div><div class="vulcanizados">Vulcanizados: -</div></div></div>
            <div class="press-item"><div class="press-id highlight">500A</div><div class="press-stats"><div class="despachados">Despachados: -</div><div class="vulcanizados">Vulcanizados: -</div></div></div>
            <div class="press-item"><div class="press-id highlight">500B</div><div class="press-stats"><div class="despachados">Despachados: -</div><div class="vulcanizados">Vulcanizados: -</div></div></div>
            <div class="press-item"><div class="press-id highlight">600A</div><div class="press-stats"><div class="despachados">Despachados: -</div><div class="vulcanizados">Vulcanizados: -</div></div></div>
            <div class="press-item"><div class="press-id highlight">600B</div><div class="press-stats"><div class="despachados">Despachados: -</div><div class="vulcanizados">Vulcanizados: -</div></div></div>
        `;
        setIndicatorColor('ind-press-delivery', null);
    }

    function fetchConveyorFullData(start = '', end = '') {
        let url = '/api/conveyor-full';
        if (start && end) {
            url += `?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`;
        }
        document.getElementById('conv-total').textContent = '...';
        document.getElementById('conv-total-display').textContent = '... min';
        document.getElementById('conv-freq').textContent = '...';
        setIndicatorColor('ind-conveyor-full', null);

        fetch(url)
            .then(response => {
                if (!response.ok) throw new Error('API Response not OK');
                return response.json();
            })
            .then(data => {
                if (data.success) {
                    const total = data.total_downtime;
                    const freq = data.frequency || 0;
                    document.getElementById('conv-total').textContent = total.toFixed(2);
                    document.getElementById('conv-total-display').textContent = `${total.toFixed(2)} min`;
                    document.getElementById('conv-freq').textContent = freq;
                    setIndicatorColor('ind-conveyor-full', data.is_ok);
                } else {
                    document.getElementById('conv-total').textContent = 'Error';
                    document.getElementById('conv-total-display').textContent = 'Error';
                    document.getElementById('conv-freq').textContent = '-';
                    setIndicatorColor('ind-conveyor-full', false);
                }
            })
            .catch(error => {
                console.error('Error fetching Conveyor Full data:', error);
                document.getElementById('conv-total').textContent = 'Error';
                document.getElementById('conv-total-display').textContent = 'Error';
                document.getElementById('conv-freq').textContent = '-';
                setIndicatorColor('ind-conveyor-full', false);
            });
    }

    function fetchPLCConveyorData() {
        const start = getStartDateTime();
        const end   = getEndDateTime();

        // Reset visual state
        ['cc01', 'cc02', 'cc03'].forEach(id => {
            document.getElementById(`${id}-val`).textContent = '...';
            document.getElementById(`${id}-runtime`).textContent = '...';
            setIndicatorColor(`ind-${id}`, null);
        });
        setIndicatorColor('ind-downtime-conveyor', null);

        let url = '/api/plc-conveyor';
        if (start && end) {
            url += `?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`;
        }

        fetch(url)
            .then(response => {
                if (!response.ok) throw new Error('API Response not OK');
                return response.json();
            })
            .then(data => {
                if (!data.success) throw new Error('API returned failure');

                // Sin datos históricos aún
                if (data.message && Object.keys(data.data).length === 0) {
                    ['cc01', 'cc02', 'cc03'].forEach(id => {
                        document.getElementById(`${id}-val`).textContent = 'Sin datos';
                        document.getElementById(`${id}-runtime`).textContent = 'Sin datos';
                        setIndicatorColor(`ind-${id}`, null);
                    });
                    setIndicatorColor('ind-downtime-conveyor', null);
                    return;
                }

                let anyError = false;
                ['CC01', 'CC02', 'CC03'].forEach(label => {
                    const id = label.toLowerCase();
                    const plc = data.data[label];
                    if (!plc || plc.status === 'error') {
                        document.getElementById(`${id}-val`).textContent = 'Error';
                        document.getElementById(`${id}-runtime`).textContent = 'Error';
                        setIndicatorColor(`ind-${id}`, false);
                        anyError = true;
                    } else {
                        const faulted = plc.faulted_minutes;
                        const runtime = plc.runtime_minutes;
                        const valEl = document.getElementById(`${id}-val`);
                        const runEl = document.getElementById(`${id}-runtime`);

                        valEl.textContent = faulted !== null ? faulted : '-';
                        runEl.textContent = runtime !== null ? runtime : '-';

                        if (faulted !== null && runtime !== null) {
                            const isOk = faulted === 0 || runtime > faulted;
                            setIndicatorColor(`ind-${id}`, isOk);
                            if (!isOk) anyError = true;
                            valEl.style.color = isOk ? 'var(--text-main)' : 'var(--danger-color)';
                            valEl.style.fontWeight = isOk ? 'normal' : '600';
                        } else {
                            setIndicatorColor(`ind-${id}`, null);
                        }
                    }
                });
                setIndicatorColor('ind-downtime-conveyor', !anyError);
            })
            .catch(error => {
                console.error('Error fetching PLC Conveyor data:', error);
                ['cc01', 'cc02', 'cc03'].forEach(id => {
                    document.getElementById(`${id}-val`).textContent = 'Error';
                    document.getElementById(`${id}-runtime`).textContent = 'Error';
                    setIndicatorColor(`ind-${id}`, false);
                });
                setIndicatorColor('ind-downtime-conveyor', false);
            });
    }


    function fetchCranePerformanceData() {
        const start = getStartDateTime();
        const end   = getEndDateTime();

        document.getElementById('crane-uptime').textContent = '...';
        document.getElementById('crane-top-downtime').textContent = '...';
        document.getElementById('crane-top-minor').textContent = '...';
        setIndicatorColor('ind-crane', null);

        let url = '/api/crane-performance';
        if (start && end) {
            url += `?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`;
        }

        fetch(url)
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

                const topDowntime = sorted.filter(a => a.downtime_minutes > 10).slice(0, 5);
                const topMinor = sorted.filter(a => a.downtime_minutes > 0 && a.downtime_minutes <= 10).slice(0, 5);

                const formatAisles = (list) => {
                    if (list.length === 0) return 'N/A';
                    return list.map(a => `Aisle ${a.aisle} (${a.downtime_minutes}m)`).join(', ');
                };

                // Si no hay > 10, mostramos los mayores en general que sean > 0
                const finalTopDowntime = topDowntime.length > 0 ? topDowntime : sorted.filter(a => a.downtime_minutes > 0).slice(0, 5);

                document.getElementById('crane-top-downtime').textContent = formatAisles(finalTopDowntime);
                document.getElementById('crane-top-minor').textContent = formatAisles(topMinor);
            })
            .catch(error => {
                console.error('Error fetching Crane Performance data:', error);
                document.getElementById('crane-uptime').textContent = 'Error';
                document.getElementById('crane-top-downtime').textContent = 'Error';
                document.getElementById('crane-top-minor').textContent = 'Error';
                setIndicatorColor('ind-crane', false);
            });
    }

    function fetchAllData() {
        fetchInputOutputData();
        fetchConveyorFullData(getStartDateTime(), getEndDateTime());
        fetchPLCConveyorData();
        fetchCranePerformanceData();

        
        const startVal = getStartDateTime();
        const endVal = getEndDateTime();
        
        // 160000 = No Tire (Objective: 0.50%)
        fetchDowntimeData('160000', startVal, endVal, 'no-tire-total-percent', 'no-tire-total-min', 'nt', 'ind-no-tire', 0.50);
        
        // 210002 = PM Robot (Objective: 1.00%)
        fetchDowntimeData('210002', startVal, endVal, 'pm-total-percent', 'pm-total-min', 'pm', 'ind-pm', 1.00);
        
        // 40000 = PM General (Objective: 1.00%)
        fetchDowntimeData('40000', startVal, endVal, 'pmg-total-percent', 'pmg-total-min', 'pmg', 'ind-pmg', 1.00);
    }


    btnQuery.addEventListener('click', () => {
        if (!startDateInput.value || !startTimeInput.value || !endDateInput.value || !endTimeInput.value) {
            alert('Por favor seleccione fecha y hora de inicio y fin.');
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

    // Program presets
    document.getElementById('preset-turn-day').addEventListener('click', () => {
        const baseDate = getSelectedBaseDate();
        startDateInput.value = baseDate;
        startTimeInput.value = "06:00";
        endDateInput.value = baseDate;
        endTimeInput.value = "14:00";
        fetchAllData();
    });

    document.getElementById('preset-turn-afternoon').addEventListener('click', () => {
        const baseDate = getSelectedBaseDate();
        startDateInput.value = baseDate;
        startTimeInput.value = "14:00";
        endDateInput.value = baseDate;
        endTimeInput.value = "22:00";
        fetchAllData();
    });

    document.getElementById('preset-turn-night').addEventListener('click', () => {
        const baseDate = getSelectedBaseDate();
        const parts = baseDate.split('-');
        const d = new Date(parts[0], parts[1] - 1, parts[2]);
        const dBefore = new Date(d.getTime() - 24 * 60 * 60 * 1000);
        
        startDateInput.value = formatDate(dBefore);
        startTimeInput.value = "22:00";
        endDateInput.value = baseDate;
        endTimeInput.value = "06:00";
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
