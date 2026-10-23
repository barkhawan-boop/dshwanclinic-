(() => {
  const root = document.querySelector('main.container');
  if (!root) return;
  const csrf = root.dataset.csrf || '';
  const roster = document.querySelector('#video-roster');
  const status = document.querySelector('#call-status');
  const stage = document.querySelector('#video-stage');
  const localVideo = document.querySelector('#local-video');
  const remoteVideo = document.querySelector('#remote-video');
  const chatPanel = document.querySelector('#chat-panel');
  let activeCall = '';
  let peer = null;
  let localStream = null;
  let pendingIce = [];
  let receivedOffer = false;
  let pollBusy = false;

  async function request(path, body) {
    const response = await fetch(path, {
      method: body ? 'POST' : 'GET',
      credentials: 'same-origin',
      cache: 'no-store',
      headers: body ? { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf } : {},
      body: body ? JSON.stringify(body) : undefined
    });
    const value = await response.json();
    if (!response.ok) throw new Error(value.error || 'Request failed');
    return value;
  }

  async function getMedia() {
    if (localStream) return localStream;
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error('This browser needs a secure HTTPS connection to use camera and microphone on other PCs.');
    }
    localStream = await navigator.mediaDevices.getUserMedia({ audio: true, video: true });
    if (localVideo) localVideo.srcObject = localStream;
    if (stage) stage.hidden = false;
    syncControls();
    return localStream;
  }

  function syncControls() {
    const audio = localStream?.getAudioTracks() || [];
    const video = localStream?.getVideoTracks() || [];
    const mute = document.querySelector('#mute');
    const camera = document.querySelector('#camera');
    if (mute) { mute.disabled = !audio.length; mute.textContent = audio.length && audio.every(t => t.enabled) ? 'Mute microphone' : 'Unmute microphone'; }
    if (camera) { camera.disabled = !video.length; camera.textContent = video.length && video.every(t => t.enabled) ? 'Turn camera off' : 'Turn camera on'; }
  }

  function ensurePeer(callId) {
    if (peer) return peer;
    peer = new RTCPeerConnection({ iceServers: [] });
    peer.ontrack = event => { if (remoteVideo) remoteVideo.srcObject = event.streams[0]; };
    peer.onicecandidate = event => {
      if (event.candidate) request('/api/call', { action: 'signal', call_id: callId, payload: { type: 'ice', candidate: event.candidate } }).catch(showError);
    };
    peer.onconnectionstatechange = () => {
      if (status) status.textContent = `Call connection: ${peer.connectionState}`;
    };
    if (localStream) localStream.getTracks().forEach(track => peer.addTrack(track, localStream));
    return peer;
  }

  async function startCall(user) {
    try {
      await getMedia();
      const result = await request('/api/call', { action: 'start', to: user.id });
      activeCall = result.call_id;
      const pc = ensurePeer(activeCall);
      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);
      await request('/api/call', { action: 'signal', call_id: activeCall, payload: { type: 'offer', sdp: pc.localDescription.sdp } });
      if (status) status.textContent = `Calling ${user.name}…`;
      if (stage) stage.hidden = false;
    } catch (error) { showError(error); await stopMedia(); }
  }

  async function acceptCall(call) {
    try {
      await getMedia();
      activeCall = call.id;
      const pc = ensurePeer(activeCall);
      const signals = await request(`/api/signals?call_id=${encodeURIComponent(activeCall)}`);
      const offer = signals.find(s => JSON.parse(s.payload).type === 'offer');
      if (!offer) throw new Error('The caller’s offer has not arrived yet. Please try again.');
      await handleSignal(offer);
      await request('/api/call', { action: 'accept', call_id: activeCall });
      if (status) status.textContent = `In a call with ${call.caller}`;
      if (stage) stage.hidden = false;
    } catch (error) { showError(error); await stopMedia(); activeCall = ''; }
  }

  async function handleSignal(signal) {
    const data = JSON.parse(signal.payload);
    const pc = ensurePeer(signal.call_id);
    if (data.type === 'offer' && !receivedOffer) {
      receivedOffer = true;
      await pc.setRemoteDescription({ type: 'offer', sdp: data.sdp });
      for (const candidate of pendingIce) await pc.addIceCandidate(candidate);
      pendingIce = [];
      const answer = await pc.createAnswer();
      await pc.setLocalDescription(answer);
      await request('/api/call', { action: 'signal', call_id: signal.call_id, payload: { type: 'answer', sdp: pc.localDescription.sdp } });
    } else if (data.type === 'answer' && !pc.remoteDescription) {
      await pc.setRemoteDescription({ type: 'answer', sdp: data.sdp });
      for (const candidate of pendingIce) await pc.addIceCandidate(candidate);
      pendingIce = [];
    } else if (data.type === 'ice') {
      if (pc.remoteDescription) await pc.addIceCandidate(data.candidate);
      else pendingIce.push(data.candidate);
    }
  }

  async function endCall(send = true) {
    if (send && activeCall) request('/api/call', { action: 'end', call_id: activeCall }).catch(() => {});
    activeCall = '';
    peer?.close(); peer = null;
    receivedOffer = false; pendingIce = [];
    await stopMedia();
    if (stage) stage.hidden = true;
    if (status) status.textContent = 'Call ended';
  }

  async function stopMedia() {
    if (localStream) localStream.getTracks().forEach(track => track.stop());
    localStream = null;
    if (localVideo) localVideo.srcObject = null;
    if (remoteVideo) remoteVideo.srcObject = null;
    syncControls();
  }

  function beep() {
    try {
      const context = new AudioContext();
      const oscillator = context.createOscillator();
      const gain = context.createGain();
      oscillator.frequency.value = 880;
      gain.gain.value = 0.06;
      oscillator.connect(gain); gain.connect(context.destination);
      oscillator.start(); oscillator.stop(context.currentTime + .32);
      oscillator.onended = () => context.close();
    } catch (_) { /* Ringing card remains visible if sound is blocked. */ }
  }

  function showError(error) { if (status) status.textContent = error?.message || String(error); }

  async function loadRoster() {
    try {
      const users = await request('/api/online');
      if (!roster) return;
      roster.replaceChildren();
      if (!users.length) { roster.innerHTML = '<div class="empty-state"><span>◎</span><h3>No colleagues online</h3><p>Signed-in users appear here while active.</p></div>'; return; }
      for (const user of users) {
        const card = document.createElement('article'); card.className = 'video-user';
        const dot = document.createElement('i'); dot.className = 'live-dot';
        const name = document.createElement('strong'); name.textContent = user.name;
        const role = document.createElement('small'); role.textContent = user.role.replaceAll('_', ' ');
        const button = document.createElement('button'); button.className = 'btn gold small'; button.type = 'button'; button.textContent = 'Call';
        button.addEventListener('click', () => startCall(user));
        card.append(dot, name, role, button); roster.append(card);
      }
    } catch (error) { showError(error); }
  }

  async function poll() {
    if (pollBusy) return;
    pollBusy = true;
    try {
      const calls = await request('/api/calls');
      const incoming = calls.find(c => c.recipient_id === Number(root.dataset.userId) && c.state === 'ringing');
      if (incoming && !activeCall && !document.querySelector(`[data-call="${incoming.id}"]`)) {
        beep();
        const card = document.createElement('section'); card.className = 'incoming-call'; card.dataset.call = incoming.id;
        const text = document.createElement('strong'); text.textContent = `${incoming.caller} is calling`;
        const accept = document.createElement('button'); accept.className = 'btn gold small'; accept.textContent = 'Answer'; accept.onclick = () => acceptCall(incoming);
        const decline = document.createElement('button'); decline.className = 'btn outline small'; decline.textContent = 'Decline'; decline.onclick = () => request('/api/call', { action: 'decline', call_id: incoming.id }).catch(showError).finally(() => card.remove());
        card.append(text, accept, decline); (roster?.parentElement || root).prepend(card);
      }
      if (activeCall) {
        const call = calls.find(c => c.id === activeCall);
        if (!call || ['ended', 'declined'].includes(call.state)) { await endCall(false); if (status) status.textContent = call?.state === 'declined' ? 'Call declined' : 'Call ended'; }
        else {
          const signals = await request(`/api/signals?call_id=${encodeURIComponent(activeCall)}`);
          for (const signal of signals) await handleSignal(signal);
        }
      }
    } catch (_) { /* transient LAN poll; next heartbeat retries */ }
    finally { pollBusy = false; }
  }

  document.querySelector('#mute')?.addEventListener('click', () => { (localStream?.getAudioTracks() || []).forEach(t => t.enabled = !t.enabled); syncControls(); });
  document.querySelector('#camera')?.addEventListener('click', () => { (localStream?.getVideoTracks() || []).forEach(t => t.enabled = !t.enabled); syncControls(); });
  document.querySelector('#hangup')?.addEventListener('click', () => endCall(true));
  if (roster) { loadRoster(); setInterval(loadRoster, 20000); }
  if (root.dataset.userId) setInterval(poll, 1200);
  if (root.dataset.userId) setInterval(() => fetch('/api/presence', { credentials: 'same-origin', cache: 'no-store' }).catch(() => {}), 30000);

  if (chatPanel) {
    const peerSelect = document.querySelector('#chat-peer');
    const messages = document.querySelector('#chat-messages');
    const chatForm = document.querySelector('#chat-form');
    const input = document.querySelector('#chat-text');
    async function loadMessages() {
      if (!peerSelect?.value) return;
      try {
        const list = await request(`/api/messages?peer=${encodeURIComponent(peerSelect.value)}`);
        const signature = list.map(m => m.id).join(',');
        if (messages.dataset.signature === signature) return;
        messages.dataset.signature = signature;
        messages.replaceChildren();
        for (const item of list) {
          const row = document.createElement('article');
          row.className = `chat-bubble${String(item.sender_id) === root.dataset.userId ? ' mine' : ''}`;
          const title = document.createElement('strong'); title.textContent = item.sender;
          const body = document.createElement('p'); body.textContent = item.body;
          const time = document.createElement('small'); time.textContent = item.created_at;
          row.append(title, body, time); messages.append(row);
        }
        messages.scrollTop = messages.scrollHeight;
      } catch (error) { showError(error); }
    }
    peerSelect?.addEventListener('change', () => { messages.dataset.signature = ''; loadMessages(); });
    chatForm?.addEventListener('submit', async event => {
      event.preventDefault();
      const body = input.value.trim();
      if (!body || !peerSelect.value) return;
      try { await request('/api/message', { to: Number(peerSelect.value), body }); input.value = ''; await loadMessages(); }
      catch (error) { showError(error); }
    });
    loadMessages(); setInterval(loadMessages, 3000);
  }
})();
