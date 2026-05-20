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

    // Update clock immediately and then every second
    updateClock();
    setInterval(updateClock, 1000);

    // Theme toggle functionality
    const themeToggleBtn = document.getElementById('theme-toggle');
    const themeIcon = document.getElementById('theme-icon');
    
    // Check for saved theme preference, otherwise use system preference
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
            // Moon icon for light mode (to switch to dark)
            themeIcon.innerHTML = '<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/>';
        } else {
            // Sun icon for dark mode (to switch to light)
            themeIcon.innerHTML = '<circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/>';
        }
    }


    /**
     * Future Data Fetching Logic (Placeholders)
     * 
     * Here you can add your AJAX / Fetch calls to get data from your internal DB.
     * Example structure:
     */

    function fetchInputOutputData() {
        fetch('api_io_data.php')
            .then(response => response.json())
            .then(data => {
                document.getElementById('io-entrada-val').innerHTML = `${data.entrada} <small>tires</small>`;
                document.getElementById('io-entrada-rate').innerHTML = `Rate= ${data.rate_entrada} <small>tires/m</small>`;
                
                document.getElementById('io-manual-val').innerHTML = `${data.manual} <small>tires</small>`;
                document.getElementById('io-manual-rate').innerHTML = `Rate= ${data.rate_manual} <small>tires/m</small>`;
                
                document.getElementById('io-auto-val').innerHTML = `${data.auto} <small>tires</small>`;
                document.getElementById('io-auto-rate').innerHTML = `Rate= ${data.rate_auto} <small>tires/m</small>`;
            })
            .catch(error => console.error('Error fetching IO data:', error));
    }

    // Initial fetch
    fetchInputOutputData();

    setInterval(() => {
        fetchInputOutputData();
    }, 30000); // Update every 30 seconds

    // No Tire Filtering Logic
    const liveCheckbox = document.getElementById('live-checkbox');
    const liveLabel = document.getElementById('live-label');
    const startTimeInput = document.getElementById('start-time');
    const endTimeInput = document.getElementById('end-time');
    const btnQuery = document.getElementById('btn-query');

    let isLiveMode = true;
    let noTireInterval = null;

    // Helper to format Date object to YYYY-MM-DDTHH:mm local time
    function formatToLocalInput(date) {
        const yyyy = date.getFullYear();
        const mm = String(date.getMonth() + 1).padStart(2, '0');
        const dd = String(date.getDate()).padStart(2, '0');
        const hh = String(date.getHours()).padStart(2, '0');
        const min = String(date.getMinutes()).padStart(2, '0');
        return `${yyyy}-${mm}-${dd}T${hh}:${min}`;
    }

    // Set default date values (Start: 24h ago, End: now)
    function setInputDefaultDates() {
        const now = new Date();
        const yesterday = new Date(now.getTime() - 24 * 60 * 60 * 1000);
        startTimeInput.value = formatToLocalInput(yesterday);
        endTimeInput.value = formatToLocalInput(now);
    }

    setInputDefaultDates();

    function fetchNoTireData(start = '', end = '') {
        let url = 'api_no_tire.php';
        if (start && end) {
            url += `?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`;
        }
        
        // Show loading state in elements
        document.getElementById('no-tire-total-percent').textContent = '...';
        document.getElementById('no-tire-total-min').textContent = '...';
        
        fetch(url)
            .then(response => {
                if (!response.ok) throw new Error('API Response not OK');
                return response.json();
            })
            .then(data => {
                if (data.success) {
                    // Update header KPIs
                    document.getElementById('no-tire-total-percent').textContent = data.downtime_percent.toFixed(2);
                    document.getElementById('no-tire-total-min').textContent = data.total_downtime.toFixed(2);
                    
                    // If in Live mode, update inputs to reflect the sliding 24-hour window
                    if (isLiveMode && data.query_start && data.query_end) {
                        const toLocalInputFormat = (str) => {
                            const parts = str.split(' ');
                            const datePart = parts[0].replace(/\//g, '-');
                            const timePart = parts[1].substring(0, 5); // HH:mm
                            return `${datePart}T${timePart}`;
                        };
                        startTimeInput.value = toLocalInputFormat(data.query_start);
                        endTimeInput.value = toLocalInputFormat(data.query_end);
                    }

                    // Update cells
                    const groups = ['100A', '100B', '200A', '200B', '300A', '300B', '400A', '400B', '500A', '500B', '600A', '600B'];
                    groups.forEach(g => {
                        const cellId = `nt-${g.toLowerCase()}`;
                        const cellEl = document.getElementById(cellId);
                        if (cellEl) {
                            const val = data.downtime_by_group[g] !== undefined ? data.downtime_by_group[g] : 0;
                            // Show "0" if value is 0 as requested
                            cellEl.textContent = val > 0 ? `${val.toFixed(2)} min` : '0';
                            
                            // Dynamic color based on value
                            if (val > 0) {
                                cellEl.style.fontWeight = '600';
                                cellEl.style.color = 'var(--danger-color)';
                            } else {
                                cellEl.style.fontWeight = 'normal';
                                cellEl.style.color = 'var(--text-main)';
                            }
                        }
                    });
                }
            })
            .catch(error => {
                console.error('Error fetching No Tire data:', error);
                document.getElementById('no-tire-total-percent').textContent = 'Error';
                document.getElementById('no-tire-total-min').textContent = 'Error';
            });
    }

    function fetchPreventivaData(start = '', end = '') {
        let url = 'api_preventiva.php';
        if (start && end) {
            url += `?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`;
        }
        
        // Show loading state in elements
        document.getElementById('pm-total-percent').textContent = '...';
        document.getElementById('pm-total-min').textContent = '...';
        
        fetch(url)
            .then(response => {
                if (!response.ok) throw new Error('API Response not OK');
                return response.json();
            })
            .then(data => {
                if (data.success) {
                    // Update header KPIs
                    document.getElementById('pm-total-percent').textContent = data.downtime_percent.toFixed(2);
                    document.getElementById('pm-total-min').textContent = data.total_downtime.toFixed(2);
                    
                    // Update cells
                    const groups = ['100A', '100B', '200A', '200B', '300A', '300B', '400A', '400B', '500A', '500B', '600A', '600B'];
                    groups.forEach(g => {
                        const cellId = `pm-${g.toLowerCase()}`;
                        const cellEl = document.getElementById(cellId);
                        if (cellEl) {
                            const val = data.downtime_by_group[g] !== undefined ? data.downtime_by_group[g] : 0;
                            // Show "0" if value is 0 as requested
                            cellEl.textContent = val > 0 ? `${val.toFixed(2)} min` : '0';
                            
                            // Dynamic color based on value
                            if (val > 0) {
                                cellEl.style.fontWeight = '600';
                                cellEl.style.color = 'var(--danger-color)';
                            } else {
                                cellEl.style.fontWeight = 'normal';
                                cellEl.style.color = 'var(--text-main)';
                            }
                        }
                    });
                }
            })
            .catch(error => {
                console.error('Error fetching Preventive data:', error);
                document.getElementById('pm-total-percent').textContent = 'Error';
                document.getElementById('pm-total-min').textContent = 'Error';
            });
    }

    function fetchPreventivaGeneralData(start = '', end = '') {
        let url = 'api_preventiva_general.php';
        if (start && end) {
            url += `?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`;
        }
        
        // Show loading state in elements
        document.getElementById('pmg-total-percent').textContent = '...';
        document.getElementById('pmg-total-min').textContent = '...';
        
        fetch(url)
            .then(response => {
                if (!response.ok) throw new Error('API Response not OK');
                return response.json();
            })
            .then(data => {
                if (data.success) {
                    // Update header KPIs
                    document.getElementById('pmg-total-percent').textContent = data.downtime_percent.toFixed(2);
                    document.getElementById('pmg-total-min').textContent = data.total_downtime.toFixed(2);
                    
                    // Update cells
                    const groups = ['100A', '100B', '200A', '200B', '300A', '300B', '400A', '400B', '500A', '500B', '600A', '600B'];
                    groups.forEach(g => {
                        const cellId = `pmg-${g.toLowerCase()}`;
                        const cellEl = document.getElementById(cellId);
                        if (cellEl) {
                            const val = data.downtime_by_group[g] !== undefined ? data.downtime_by_group[g] : 0;
                            // Show "0" if value is 0 as requested
                            cellEl.textContent = val > 0 ? `${val.toFixed(2)} min` : '0';
                            
                            // Dynamic color based on value
                            if (val > 0) {
                                cellEl.style.fontWeight = '600';
                                cellEl.style.color = 'var(--danger-color)';
                            } else {
                                cellEl.style.fontWeight = 'normal';
                                cellEl.style.color = 'var(--text-main)';
                            }
                        }
                    });
                }
            })
            .catch(error => {
                console.error('Error fetching Preventive General data:', error);
                document.getElementById('pmg-total-percent').textContent = 'Error';
                document.getElementById('pmg-total-min').textContent = 'Error';
            });
    }

    // Toggle Checkbox event listener
    liveCheckbox.addEventListener('change', () => {
        isLiveMode = liveCheckbox.checked;
        
        if (isLiveMode) {
            // Enable Live Mode
            liveLabel.textContent = 'En Vivo 🟢';
            startTimeInput.disabled = true;
            endTimeInput.disabled = true;
            btnQuery.disabled = true;
            
            setInputDefaultDates();
            fetchNoTireData();
            fetchPreventivaData();
            fetchPreventivaGeneralData();
            startAutoRefresh();
        } else {
            // Enable Historical Mode
            liveLabel.textContent = 'Histórico 📅';
            startTimeInput.disabled = false;
            endTimeInput.disabled = false;
            btnQuery.disabled = false;
            
            stopAutoRefresh();
        }
    });

    btnQuery.addEventListener('click', () => {
        const startVal = startTimeInput.value;
        const endVal = endTimeInput.value;
        if (!startVal || !endVal) {
            alert('Por favor seleccione fecha de inicio y fin.');
            return;
        }
        fetchNoTireData(startVal, endVal);
        fetchPreventivaData(startVal, endVal);
        fetchPreventivaGeneralData(startVal, endVal);
    });

    function startAutoRefresh() {
        stopAutoRefresh();
        noTireInterval = setInterval(() => {
            if (isLiveMode) {
                fetchNoTireData();
                fetchPreventivaData();
                fetchPreventivaGeneralData();
            }
        }, 30000); // 30 seconds
    }

    function stopAutoRefresh() {
        if (noTireInterval) {
            clearInterval(noTireInterval);
            noTireInterval = null;
        }
    }

    // Initial load
    fetchNoTireData();
    fetchPreventivaData();
    fetchPreventivaGeneralData();
    startAutoRefresh();
});
