// --- STATE & DOM ---
const feedContainer = document.getElementById('feed-container');
const fleetBody = document.getElementById('fleet-body');
const alertBanner = document.getElementById('critical-alerts-banner');
const ticketsBody = document.getElementById('tickets-body');

const authView = document.getElementById('auth-view');
const dashboardView = document.getElementById('dashboard-view');
const logoutBtn = document.getElementById('logout-btn');
const farmIdDisplay = document.getElementById('farm-id-display');
const connectionStatus = document.getElementById('connection-status');

let fleetState = {};
let ws = null;
let isLoginMode = true;

// --- AUTH LOGIC ---
function getToken() {
    return localStorage.getItem('ls_token');
}

function getFarmId() {
    return localStorage.getItem('ls_farm_id');
}

function setAuth(token, farmId) {
    localStorage.setItem('ls_token', token);
    localStorage.setItem('ls_farm_id', farmId);
}

function logout() {
    localStorage.removeItem('ls_token');
    localStorage.removeItem('ls_farm_id');
    if (ws) {
        ws.close();
        ws = null;
    }
    showAuthView();
}

function toggleAuthMode() {
    isLoginMode = !isLoginMode;
    document.getElementById('auth-title').innerText = isLoginMode ? 'SYSTEM LOGIN' : 'SYSTEM REGISTRATION';
    document.getElementById('auth-submit').innerText = isLoginMode ? 'LOGIN' : 'REGISTER';
    document.getElementById('auth-toggle-text').innerText = isLoginMode ? 'No account?' : 'Already have an account?';
    document.getElementById('auth-error').style.display = 'none';
}

async function submitAuth() {
    const user = document.getElementById('auth-username').value.trim();
    const pass = document.getElementById('auth-password').value.trim();
    const errorDiv = document.getElementById('auth-error');
    
    if (!user || !pass) {
        errorDiv.innerText = "Username and password required.";
        errorDiv.style.display = "block";
        return;
    }
    
    const endpoint = isLoginMode ? '/auth/login' : '/auth/register';
    const payload = { username: user, password: pass };
    
    try {
        const res = await fetch(endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        
        const data = await res.json();
        
        if (!res.ok) {
            errorDiv.innerText = data.detail || "Authentication failed.";
            errorDiv.style.display = "block";
        } else {
            if (isLoginMode) {
                setAuth(data.access_token, data.farm_id);
                showDashboardView();
            } else {
                // Auto-login after registration or tell them to login
                errorDiv.style.color = "#10b981"; // green
                errorDiv.innerText = "Registration successful. Please login.";
                errorDiv.style.display = "block";
                toggleAuthMode();
            }
        }
    } catch (e) {
        errorDiv.innerText = "Network error.";
        errorDiv.style.display = "block";
    }
}

// --- VIEW MANAGEMENT ---
function showAuthView() {
    authView.style.display = 'flex';
    dashboardView.style.display = 'none';
    logoutBtn.style.display = 'none';
    farmIdDisplay.innerText = '';
    connectionStatus.innerText = 'OFFLINE (UNAUTH)';
    connectionStatus.style.color = '#6b7280';
}

function showDashboardView() {
    authView.style.display = 'none';
    dashboardView.style.display = 'block';
    logoutBtn.style.display = 'inline-block';
    farmIdDisplay.innerText = `FARM: ${getFarmId()}`;
    connectionStatus.innerText = 'CONNECTING...';
    
    fleetState = {};
    renderTable();
    feedContainer.innerHTML = '';
    
    fetchInitialData();
    connectWebSocket();
}

// --- API FETCH WRAPPER ---
async function apiFetch(url, options = {}) {
    const token = getToken();
    if (!options.headers) options.headers = {};
    if (token) {
        options.headers['Authorization'] = `Bearer ${token}`;
    }
    const res = await fetch(url, options);
    if (res.status === 401) {
        logout();
        throw new Error('Unauthorized');
    }
    return res;
}

// --- DASHBOARD DATA ---
async function fetchInitialData() {
    try {
        const herdRes = await apiFetch('/api/cows');
        if (herdRes.ok) {
            const cows = await herdRes.json();
            cows.forEach(c => {
                fleetState[c.cow_id] = {
                    cow_id: c.cow_id,
                    timestamp: 'NO DATA',
                    mobility_score: '-',
                    ai_prediction: 'UNKNOWN'
                };
            });
            renderTable();
        }
        await fetchTickets();
    } catch(e) {
        console.error("Initial data fetch failed", e);
    }
}

// --- WEBSOCKET ---
function connectWebSocket() {
    if (ws) ws.close();
    const token = getToken();
    if (!token) return;
    
    ws = new WebSocket(`ws://${window.location.host}/ws/dashboard?token=${token}`);
    
    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        if (data.type === 'TELEMETRY_UPDATE') {
            const cow = {
                cow_id: data.cow_id,
                timestamp: data.timestamp,
                mobility_score: data.mobility_score,
                ai_prediction: data.ai_prediction
            };
            if (!fleetState[data.cow_id]) {
                fleetState[data.cow_id] = cow;
            } else {
                Object.assign(fleetState[data.cow_id], cow);
            }
            addFeedEntry(cow);
            renderTable();
        } else if (data.type === 'TICKET_UPDATE') {
            fetchTickets();
        }
    };

    ws.onopen = () => {
        connectionStatus.innerText = 'SYSTEM ONLINE';
        connectionStatus.style.color = '#000000';
    };

    ws.onclose = (e) => {
        if (e.code === 1008) {
            logout();
        } else if (getToken()) {
            connectionStatus.innerText = 'RECONNECTING...';
            setTimeout(connectWebSocket, 5000);
        }
    };
}

// --- UI RENDERING ---
function renderTable() {
    fleetBody.innerHTML = '';
    let hasSCM = false;
    
    const cows = Object.values(fleetState);
    if (cows.length === 0) {
        fleetBody.innerHTML = `<tr><td colspan="5" style="text-align:center; color:#6b7280; font-style:italic;">No cows registered in this farm. Add one to begin monitoring.</td></tr>`;
        alertBanner.style.display = 'none';
        return;
    }

    cows.forEach(cow => {
        const row = document.createElement('tr');
        
        let statusBadge = `<span class="status-badge">${cow.ai_prediction}</span>`;
        if (cow.ai_prediction === 'SCM_DETECTED') {
            statusBadge = `<span class="status-badge scm">${cow.ai_prediction}</span>`;
            hasSCM = true;
        } else if (cow.ai_prediction === 'UNKNOWN') {
            statusBadge = `<span class="status-badge" style="color:#6b7280; border-color:#6b7280;">UNKNOWN</span>`;
        }

        let cowIdDisplay = cow.cow_id;
        if (cowIdDisplay.length > 20) {
            cowIdDisplay = `<span style="display:inline-block; max-width: 150px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;" title="${cow.cow_id}">${cow.cow_id}</span>`;
        }

        row.innerHTML = `
            <td><strong>${cowIdDisplay}</strong></td>
            <td>${cow.timestamp !== 'NO DATA' ? new Date(cow.timestamp).toLocaleTimeString() : 'OFFLINE'}</td>
            <td>${typeof cow.mobility_score === 'number' ? cow.mobility_score.toFixed(2) : cow.mobility_score}</td>
            <td>${statusBadge}</td>
            <td><button class="action-btn" onclick="openConsult('${cow.cow_id}')" ${cow.ai_prediction === 'UNKNOWN' ? 'disabled style="opacity:0.5; cursor:not-allowed;"' : ''}>CONSULT</button></td>
        `;
        fleetBody.appendChild(row);
    });

    alertBanner.style.display = hasSCM ? 'block' : 'none';
}

function addFeedEntry(cow) {
    const entry = document.createElement('div');
    entry.className = 'feed-entry';
    if (cow.ai_prediction === 'SCM_DETECTED') {
        entry.classList.add('alert');
    }
    entry.textContent = `[${new Date(cow.timestamp).toISOString()}] INGEST: ${cow.cow_id} | MOB: ${cow.mobility_score.toFixed(2)} | PRED: ${cow.ai_prediction}`;
    
    feedContainer.prepend(entry);
    if (feedContainer.children.length > 100) {
        feedContainer.removeChild(feedContainer.lastChild);
    }
}

// --- TICKETS ---
async function fetchTickets() {
    try {
        const res = await apiFetch('/api/tickets');
        if (res.ok) {
            const tickets = await res.json();
            renderTickets(tickets);
        }
    } catch(e) {}
}

function renderTickets(tickets) {
    ticketsBody.innerHTML = '';
    if (tickets.length === 0) {
        ticketsBody.innerHTML = `<tr><td colspan="3" style="text-align:center; color:#6b7280; font-style:italic;">No open tickets</td></tr>`;
        return;
    }
    
    tickets.forEach(t => {
        const row = document.createElement('tr');
        let cowIdDisplay = t.cow_id;
        if (cowIdDisplay.length > 20) {
            cowIdDisplay = `<span style="display:inline-block; max-width: 150px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;" title="${t.cow_id}">${t.cow_id}</span>`;
        }
        
        let actionPlanHtml = t.action_plan ? `<div class="action-plan"><strong>AGENT ACTION PLAN:</strong> ${t.action_plan}</div>` : '';

        row.innerHTML = `
            <td>#${t.id}</td>
            <td><strong>${cowIdDisplay}</strong></td>
            <td>
                <div class="ticket-actions">
                    <button class="action-btn danger" onclick="resolveTicket(${t.id}, true)">CONFIRM SCM</button>
                    <button class="action-btn" onclick="resolveTicket(${t.id}, false)">FALSE ALARM</button>
                    <button class="action-btn" onclick="openConsult('${t.cow_id}')">CONSULT</button>
                </div>
                ${actionPlanHtml}
            </td>
        `;
        ticketsBody.appendChild(row);
    });
}

async function resolveTicket(ticketId, isTruePositive) {
    try {
        await apiFetch(`/api/tickets/${ticketId}/resolve`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ true_positive: isTruePositive })
        });
        fetchTickets();
    } catch(e) {}
}

// --- ADD COW MODAL ---
function openAddCowModal() {
    document.getElementById('add-cow-error').style.display = 'none';
    document.getElementById('new-cow-id').value = '';
    document.getElementById('new-collar-id').value = '';
    document.getElementById('add-cow-modal').style.display = 'block';
}

function closeAddCowModal() {
    document.getElementById('add-cow-modal').style.display = 'none';
}

async function submitAddCow() {
    const cowId = document.getElementById('new-cow-id').value.trim();
    const collarId = document.getElementById('new-collar-id').value.trim();
    const errorDiv = document.getElementById('add-cow-error');
    
    if (!cowId || !collarId) {
        errorDiv.innerText = "Tag ID and Collar ID are required.";
        errorDiv.style.display = "block";
        return;
    }
    
    try {
        const res = await apiFetch('/api/cows', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ cow_id: cowId, collar_id: collarId })
        });
        
        if (res.ok) {
            closeAddCowModal();
            fetchInitialData(); // reload herd
        } else {
            const data = await res.json();
            errorDiv.innerText = data.detail || "Failed to add cow.";
            errorDiv.style.display = "block";
        }
    } catch (e) {
        errorDiv.innerText = "Network error.";
        errorDiv.style.display = "block";
    }
}

// --- AI CARETAKER ---
const consultModal = document.getElementById('consult-modal');
const consultTitle = document.getElementById('consult-title');
const chatHistory = document.getElementById('chat-history');
const chatInput = document.getElementById('chat-input');
const chatImageInput = document.getElementById('chat-image');
let currentConsultCow = null;

function openConsult(cowId) {
    currentConsultCow = cowId;
    consultTitle.textContent = `AI CARETAKER // ${cowId}`;
    chatHistory.innerHTML = '<div style="text-align:center; color:#6b7280; font-size:0.8rem; margin-top:1rem;">LOADING HISTORY...</div>';
    consultModal.style.display = 'block';
    loadConsultHistory(cowId);
}

function closeConsult() {
    consultModal.style.display = 'none';
    currentConsultCow = null;
}

async function loadConsultHistory(cowId) {
    try {
        const res = await apiFetch(`/api/cows/${cowId}/chat_history`);
        if (res.ok) {
            const messages = await res.json();
            chatHistory.innerHTML = '';
            if (messages.length === 0) {
                chatHistory.innerHTML = '<div style="text-align:center; color:#6b7280; font-size:0.8rem; margin-top:1rem;">NO PREVIOUS CONSULTATION.</div>';
            } else {
                messages.forEach(m => addChatMessage(m.role, m.message));
            }
        }
    } catch (e) {
        chatHistory.innerHTML = '<div style="text-align:center; color:#ef4444; font-size:0.8rem; margin-top:1rem;">ERROR LOADING HISTORY.</div>';
    }
}

function addChatMessage(role, text) {
    if (chatHistory.innerHTML.includes('NO PREVIOUS') || chatHistory.innerHTML.includes('LOADING')) {
        chatHistory.innerHTML = '';
    }
    const msgDiv = document.createElement('div');
    msgDiv.className = `chat-msg ${role}`;
    
    if (role === 'agent') {
        msgDiv.innerHTML = marked.parse(text);
    } else {
        msgDiv.innerHTML = text;
    }
    
    chatHistory.appendChild(msgDiv);
    chatHistory.scrollTop = chatHistory.scrollHeight;
}

function handleChatKey(e) {
    if (e.key === 'Enter') {
        sendConsultMessage();
    }
}

async function sendConsultMessage() {
    const text = chatInput.value.trim();
    if (!text && (!chatImageInput.files || chatImageInput.files.length === 0)) return;
    if (!currentConsultCow) return;
    
    let base64Image = null;
    if (chatImageInput.files && chatImageInput.files.length > 0) {
        const file = chatImageInput.files[0];
        base64Image = await new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => resolve(reader.result);
            reader.onerror = reject;
            reader.readAsDataURL(file);
        });
    }

    chatInput.value = '';
    chatImageInput.value = ''; 
    chatInput.disabled = true;
    chatImageInput.disabled = true;
    
    let userDisplay = text;
    if (base64Image) {
        userDisplay += '<br><span style="font-size:0.8rem; color:#6b7280;">[IMAGE ATTACHED]</span>';
    }
    addChatMessage('user', userDisplay);
    
    try {
        const payload = { message: text || "[Attached Image]" };
        if (base64Image) {
            payload.image_base64 = base64Image;
        }

        const res = await apiFetch(`/api/cows/${currentConsultCow}/consult`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        
        if (res.ok) {
            const agentMsg = await res.json();
            addChatMessage('agent', agentMsg.message);
        } else {
            addChatMessage('agent', '[SYSTEM ERROR] FAILED TO REACH AI CARETAKER.');
        }
    } catch(e) {
        addChatMessage('agent', '[SYSTEM ERROR] CONNECTION FAILED.');
    } finally {
        chatInput.disabled = false;
        chatImageInput.disabled = false;
        chatInput.focus();
    }
}

// --- BOOTSTRAP ---
if (getToken()) {
    showDashboardView();
} else {
    showAuthView();
}
