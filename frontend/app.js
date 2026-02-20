const fileMetaEl = document.getElementById('file-meta');
const peerGridEl = document.getElementById('peer-grid');
const metricPeerCountEl = document.getElementById('metric-peer-count');
const metricCompleteEl = document.getElementById('metric-complete');
const metricPieceCountEl = document.getElementById('metric-piece-count');
const metricUpdatedEl = document.getElementById('metric-updated');
const logPeerSelectEl = document.getElementById('log-peer-select');
const logOutputEl = document.getElementById('log-output');
const peerCardTemplate = document.getElementById('peer-card-template');

let selectedPeerId = null;

function fmtBytes(bytes) {
  const units = ['B', 'KB', 'MB', 'GB'];
  let idx = 0;
  let value = bytes;
  while (value >= 1024 && idx < units.length - 1) {
    value /= 1024;
    idx += 1;
  }
  return `${value.toFixed(idx === 0 ? 0 : 1)} ${units[idx]}`;
}

function updateOverview(status) {
  const file = status.file;
  fileMetaEl.textContent = `${file.name} | ${fmtBytes(file.size)} | piece size ${fmtBytes(file.piece_size)}`;
  metricPeerCountEl.textContent = String(status.swarm.peer_count);
  metricCompleteEl.textContent = String(status.swarm.completed_peers);
  metricPieceCountEl.textContent = String(file.piece_count);
  metricUpdatedEl.textContent = new Date(status.as_of).toLocaleTimeString();
}

function renderPeerCard(peer) {
  const node = peerCardTemplate.content.firstElementChild.cloneNode(true);
  node.querySelector('.peer-title').textContent = `Peer ${peer.peer_id}`;
  node.querySelector('.peer-host').textContent = `${peer.host}:${peer.port}`;

  const badge = node.querySelector('.badge');
  if (peer.complete) {
    badge.textContent = 'Complete';
    badge.classList.add('complete');
  } else {
    badge.textContent = 'Syncing';
    badge.classList.add('syncing');
  }

  const pct = Math.round(peer.completion_ratio * 100);
  node.querySelector('.progress-fill').style.width = `${pct}%`;
  node.querySelector('.progress-text').textContent = `${peer.pieces_owned}/${peer.total_pieces} pieces (${pct}%)`;

  node.querySelector('.last-piece').textContent = peer.last_piece == null ? '-' : String(peer.last_piece);
  node.querySelector('.preferred').textContent = peer.preferred_neighbors.length ? peer.preferred_neighbors.join(', ') : '-';
  node.querySelector('.optimistic').textContent = peer.optimistic_neighbor == null ? '-' : String(peer.optimistic_neighbor);
  node.querySelector('.activity').textContent = peer.last_activity;
  return node;
}

function updatePeerGrid(status) {
  peerGridEl.innerHTML = '';
  status.peers.forEach((peer) => {
    peerGridEl.appendChild(renderPeerCard(peer));
  });
}

function ensureLogSelect(status) {
  const peerIds = status.peers.map((p) => p.peer_id);
  const knownOptions = Array.from(logPeerSelectEl.options).map((o) => Number(o.value));
  const changed = peerIds.length !== knownOptions.length || peerIds.some((id, i) => id !== knownOptions[i]);

  if (changed) {
    logPeerSelectEl.innerHTML = '';
    peerIds.forEach((peerId) => {
      const option = document.createElement('option');
      option.value = String(peerId);
      option.textContent = String(peerId);
      logPeerSelectEl.appendChild(option);
    });
  }

  if (selectedPeerId == null || !peerIds.includes(selectedPeerId)) {
    selectedPeerId = peerIds[0] ?? null;
  }

  if (selectedPeerId != null) {
    logPeerSelectEl.value = String(selectedPeerId);
  }
}

async function fetchJson(url) {
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`HTTP ${res.status} for ${url}`);
  }
  return res.json();
}

async function refreshLogs() {
  if (selectedPeerId == null) {
    logOutputEl.textContent = 'No peers available.';
    return;
  }

  try {
    const payload = await fetchJson(`/api/logs?peer_id=${selectedPeerId}`);
    logOutputEl.textContent = payload.lines.length ? payload.lines.join('\n') : 'No log lines yet for this peer.';
    logOutputEl.scrollTop = logOutputEl.scrollHeight;
  } catch (err) {
    logOutputEl.textContent = `Unable to load logs: ${err.message}`;
  }
}

async function refreshStatus() {
  try {
    const status = await fetchJson('/api/status');
    updateOverview(status);
    updatePeerGrid(status);
    ensureLogSelect(status);
  } catch (err) {
    fileMetaEl.textContent = `Unable to load status: ${err.message}`;
  }
}

logPeerSelectEl.addEventListener('change', () => {
  selectedPeerId = Number(logPeerSelectEl.value);
  refreshLogs();
});

async function tick() {
  await refreshStatus();
  await refreshLogs();
}

void tick();
setInterval(tick, 2000);
