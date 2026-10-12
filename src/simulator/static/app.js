const tbody = document.getElementById('telemetry-body');
const connStatus = document.getElementById('conn-status');
const systemLog = document.getElementById('system-log');

const MAX_ROWS = 50;

function log(msg) {
    const time = new Date().toISOString().split('T')[1].split('.')[0];
    systemLog.textContent += `\n[${time}] ${msg}`;
    systemLog.scrollTop = systemLog.scrollHeight;
}

function connect() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/stream`;
    
    log(`Connecting to ${wsUrl}...`);
    const ws = new WebSocket(wsUrl);
    
    ws.onopen = () => {
        connStatus.textContent = 'Connected (Live Stream Active)';
        connStatus.style.color = '#10b981'; // flat green
        log('WebSocket connection established.');
    };
    
    ws.onclose = () => {
        connStatus.textContent = 'Disconnected. Reconnecting...';
        connStatus.style.color = 'var(--text-main)';
        log('Connection lost. Retrying in 3s...');
        setTimeout(connect, 3000);
    };
    
    ws.onerror = (err) => {
        log(`WebSocket Error encountered.`);
    };
    
    ws.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            handleIncomingData(data);
        } catch (e) {
            log(`Failed to parse data: ${e.message}`);
        }
    };
}

function handleIncomingData(data) {
    const isWarning = data.prediction.status !== "HEALTHY";
    
    const tr = document.createElement('tr');
    if (isWarning) {
        tr.classList.add('row-warning');
        log(`SCM ALERT for ${data.cow_id}! Prob: ${(data.prediction.probability * 100).toFixed(1)}%`);
    }
    
    // Format timestamp
    const date = new Date(data.timestamp);
    const timeStr = date.toISOString().split('T')[1].split('.')[0];
    
    tr.innerHTML = `
        <td>${timeStr}</td>
        <td><strong>${data.cow_id}</strong></td>
        <td>${data.raw_data.x_mean.toFixed(2)}</td>
        <td>${data.raw_data.y_mean.toFixed(2)}</td>
        <td>${data.raw_data.z_mean.toFixed(2)}</td>
        <td>${data.raw_data.mobility.toFixed(2)}</td>
        <td>${(data.prediction.probability * 100).toFixed(2)}%</td>
        <td>${data.prediction.status}</td>
    `;
    
    // Insert at top
    tbody.insertBefore(tr, tbody.firstChild);
    
    // Trim table size
    while (tbody.children.length > MAX_ROWS) {
        tbody.removeChild(tbody.lastChild);
    }
}

// Init
connect();
