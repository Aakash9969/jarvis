(() => {
  'use strict';

  window.addEventListener('error', e => {
    console.error('Global error:', e.error || e.message);
    const chat = document.getElementById('chatInner');
    if (chat) {
      const div = document.createElement('div');
      div.style.cssText = 'color:#ff6d7e;padding:12px;font-family:monospace;font-size:12px;background:rgba(255,109,126,0.1);border:1px solid #ff6d7e;border-radius:8px;margin:8px;';
      div.textContent = 'JS Error: ' + (e.error?.message || e.message);
      chat.appendChild(div);
    }
  });
  window.addEventListener('unhandledrejection', e => {
    console.error('Unhandled rejection:', e.reason);
  });

  console.log('[JARVIS] Script loaded');

  // ---- Motion helpers ----
  const M = window.Motion;
  const animate = M ? M.animate.bind(M) : null;
  const hover = M ? M.hover.bind(M) : null;
  const press = M ? M.press.bind(M) : null;
  const stagger = M ? M.stagger.bind(M) : null;

  const EASE_OUT = [0.22, 1, 0.36, 1];

  function motionIn(el, keyframes, opts) {
    if (!animate || !el) return;
    try { animate(el, keyframes, { ease: EASE_OUT, ...opts }); } catch {}
  }
  function motionOut(el, keyframes, opts) {
    if (!animate || !el) return;
    try { animate(el, keyframes, { ease: 'easeIn', ...opts }); } catch {}
  }

  /* ---------- DOM refs (lazy) ---------- */
  let chatScroll, chatInner, orb, orbGlow, ringsA, ringsB, ringsC;
  let orbCoreInner, orbEq, orbPulseLayer, statusText, statusDot;
  let micBtn, micRing, ttsBtn, sendBtn, textIn, liveTx, activityLog, activityCountEl;
  let chips, sysUser, sysWorkspace, sysModel, sysTools, sysMemory;
  let llmPill, llmDot, llmText, clockEl, resetBtn, blobA, blobB;
  let eqBars;

  function cacheDOM() {
    chatScroll = document.getElementById('chatScroll');
    chatInner = document.getElementById('chatInner');
    orb = document.getElementById('orb');
    orbGlow = document.getElementById('orbGlow');
    ringsA = document.getElementById('ringsA');
    ringsB = document.getElementById('ringsB');
    ringsC = document.getElementById('ringsC');
    orbCoreInner = document.getElementById('orbCoreInner');
    orbEq = document.getElementById('orbEq');
    orbPulseLayer = document.getElementById('orbPulseLayer');
    statusText = document.getElementById('statusText');
    statusDot = document.getElementById('statusDot');
    micBtn = document.getElementById('micBtn');
    micRing = document.getElementById('micRing');
    ttsBtn = document.getElementById('ttsBtn');
    sendBtn = document.getElementById('sendBtn');
    textIn = document.getElementById('textIn');
    liveTx = document.getElementById('liveTx');
    activityLog = document.getElementById('activityLog');
    activityCountEl = document.getElementById('activityCount');
    chips = document.getElementById('chips');
    sysUser = document.getElementById('sysUser');
    sysWorkspace = document.getElementById('sysWorkspace');
    sysModel = document.getElementById('sysModel');
    sysTools = document.getElementById('sysTools');
    sysMemory = document.getElementById('sysMemory');
    llmPill = document.getElementById('llmPill');
    llmDot = document.getElementById('llmDot');
    llmText = document.getElementById('llmText');
    clockEl = document.getElementById('clock');
    resetBtn = document.getElementById('resetBtn');
    blobA = document.getElementById('blobA');
    blobB = document.getElementById('blobB');
    eqBars = orbEq ? orbEq.querySelectorAll('span') : [];
    console.log('[JARVIS] DOM cached:', Object.keys({chatInner, textIn, sendBtn, micBtn, orb, statusText}).filter(k => eval(k)).join(', '));
  }

  /* ---------- constants ---------- */
  const STATUS_DEFAULT = {
    idle: 'How can I help?',
    listening: 'Listening...',
    processing: 'Thinking...',
    executing: 'Working...',
    speaking: 'Speaking...',
    confirm: 'Waiting for your confirmation',
    error: 'Something went wrong'
  };

  const CHIPS = [
    ['Open Chrome', 'open chrome'],
    ['System status', 'system status'],
    ['What time is it?', 'what time is it'],
    ['Create notes.txt', 'create a file called notes.txt'],
    ['Study plan', 'write a study plan into studyplan.txt'],
    ['YouTube: Python', 'search youtube for python tutorials'],
    ['Explain recursion', 'explain recursion'],
    ['Help', 'help'],
  ];

  /* ---------- state ---------- */
  let state = 'idle';
  let statusSeq = 0;
  let speaking = false;
  let ttsMuted = false;
  let ttsVoice = null;
  let rec = null;
  let recActive = false;
  let recFinal = '';
  let meterRAF = 0;
  let audioCtx = null;
  let micStream = null;
  let analyser = null;
  let micRingAnim = null;
  let pulseTimer = null;
  let ringCAnim = null;
  let eqAnims = [];
  let activityCount = 0;
  let memCount = 0;
  let activeConfirmCard = null;

  /* ---------- utils ---------- */
  function wait(ms) { return new Promise(function(r) { setTimeout(r, ms); }); }
  function esc(s) {
    return String(s).replace(/[&<>"']/g, function(c) {
      switch (c) {
        case '&': return '&';
        case '<': return '<';
        case '>': return '>';
        case '"': return '"';
        case "'": return '&apos;';
        default: return c;
      }
    });
  }
  function timeStr() {
    return new Date().toLocaleTimeString([], { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
  }
  function shortenPath(p) {
    const parts = p.split(/[\\/]/).filter(Boolean);
    return parts.length <= 2 ? p : '...' + parts.slice(-2).join('\\');
  }

  /* ---------- markdown renderer ---------- */
  function renderMarkdown(src) {
    if (!src) return '';
    const blocks = [];
    let text = String(src).replace(/```(\w*)\n?([\s\S]*?)```/g, (m, lang, code) => {
      blocks.push('<pre><code>' + esc(code.replace(/\n$/, '')) + '</code></pre>');
      return '\u0000B' + (blocks.length - 1) + '\u0000';
    });
    text = esc(text);
    text = text.replace(/^### (.*)$/gm, '<h4>$1</h4>');
    text = text.replace(/^## (.*)$/gm, '<h3>$1</h3>');
    text = text.replace(/^# (.*)$/gm, '<h3>$1</h3>');
    text = text.replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>');
    text = text.replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, '$1<i>$2</i>');
    text = text.replace(/__([^_]+)__/g, '<b>$1</b>');
    text = text.replace(/`([^`\n]+)`/g, '<code>$1</code>');
    const lines = text.split('\n');
    let html = '', listType = null, tableBuf = [];
    const flushList = () => { if (listType) { html += listType === 'ul' ? '</ul>' : '</ol>'; listType = null; } };
    const flushTable = () => {
      if (tableBuf.length) {
        const parse = r => r.replace(/^\||\|$/g, '').split('|').map(c => c.trim());
        html += '<table>';
        tableBuf.forEach((r, idx) => {
          const cells = parse(r);
          if (cells.every(c => /^:?-{2,}:?$/.test(c) || c === '')) return;
          const tag = idx === 0 ? 'th' : 'td';
          html += '<tr>' + cells.map(c => '<' + tag + '>' + c + '</' + tag + '>').join('') + '</tr>';
        });
        html += '</table>';
        tableBuf = [];
      }
    };
    for (const rawLine of lines) {
      const line = rawLine.trim();
      if (line === '') { flushList(); flushTable(); continue; }
      if (line.startsWith('|')) { flushList(); tableBuf.push(line); continue; } else flushTable();
      const h = line.match(/^(#{1,4})\s+(.*)$/);
      if (h) { flushList(); const lvl = Math.min(h[1].length + 2, 5); html += '<h' + lvl + '>' + h[2] + '</h' + lvl + '>'; continue; }
      const ul = line.match(/^[-*]\s+(.*)$/);
      if (ul) { flushTable(); if (listType !== 'ul') { flushList(); html += '<ul>'; listType = 'ul'; } html += '<li>' + ul[1] + '</li>'; continue; }
      const ol = line.match(/^\d+\.\s+(.*)$/);
      if (ol) { flushTable(); if (listType !== 'ol') { flushList(); html += '<ol>'; listType = 'ol'; } html += '<li>' + ol[1] + '</li>'; continue; }
      flushList();
      html += '<p>' + line + '</p>';
    }
    flushList(); flushTable();
    html = html.replace(/\[ \]/g, '[ ]').replace(/\[[xX]\]/g, '[x]');
    html = html.replace(/\u0000B(\d+)\u0000/g, (m, i) => blocks[i]);
    return html;
  }

  function stripMarkdownForSpeech(text) {
    return String(text).replace(/```[\s\S]*?```/g, ' ').replace(/`([^`]+)`/g, '$1').replace(/\|/g, ' ').replace(/[*_#>-]+/g, ' ').replace(/\[(.*?)\]\(.*?\)/g, '$1').replace(/\s+/g, ' ').trim();
  }

  /* ---------- API ---------- */
  async function api(path, body) {
    try {
      const res = await fetch(path, {
        method: body ? 'POST' : 'GET',
        headers: body ? { 'Content-Type': 'application/json' } : undefined,
        body: body ? JSON.stringify(body) : undefined,
        credentials: 'omit'
      });
      if (!res.ok) throw new Error('HTTP ' + res.status);
      return res.json();
    } catch (e) {
      console.error('API error:', e);
      throw e;
    }
  }

  /* ---------- status machine ---------- */
  function setStatus(next, text) {
    const seq = ++statusSeq;
    state = next;
    document.body.dataset.state = next;
    if (orb) orb.dataset.state = next;
    const label = text || STATUS_DEFAULT[next];
    if (statusText) {
      if (animate) {
        motionOut(statusText, { opacity: [1, 0], y: [0, -6] }, { duration: 0.16 });
        setTimeout(() => {
          if (seq !== statusSeq) return;
          statusText.textContent = label;
          motionIn(statusText, { opacity: [0, 1], y: [8, 0] }, { duration: 0.3 });
        }, 150);
      } else {
        statusText.textContent = label;
      }
    }
    onOrbState(next);
  }

  function onOrbState(next) {
    if (next === 'listening') startPulseLoop(); else stopPulseLoop();
    if (next === 'speaking') startEq(); else stopEq();
    if (next === 'processing' || next === 'executing') spinInner(true);
    else spinInner(false);
  }

  function spinInner(fast) {
    if (!animate || !ringsC) return;
    ringCAnim?.stop?.();
    ringCAnim = animate(ringsC, { rotate: [0, 360] }, { duration: fast ? 7 : 22, repeat: Infinity, ease: 'linear' });
  }

  /* ---------- ambient animations ---------- */
  function startAmbient() {
    if (!animate) return;
    if (ringsA) animate(ringsA, { rotate: [0, 360] }, { duration: 48, repeat: Infinity, ease: 'linear' });
    if (ringsB) animate(ringsB, { rotate: [360, 0] }, { duration: 34, repeat: Infinity, ease: 'linear' });
    spinInner(false);
    if (orbGlow) animate(orbGlow, { opacity: [0.45, 0.8, 0.45], scale: [1, 1.07, 1] }, { duration: 4.6, repeat: Infinity, ease: 'easeInOut' });
    if (blobA) animate(blobA, { x: [0, 60, -20, 0], y: [0, -40, 20, 0] }, { duration: 26, repeat: Infinity, ease: 'easeInOut' });
    if (blobB) animate(blobB, { x: [0, -50, 30, 0], y: [0, 30, -30, 0] }, { duration: 32, repeat: Infinity, ease: 'easeInOut' });
  }

  /* ---------- pulse loop (listening) ---------- */
  function spawnPulse() {
    if (!orbPulseLayer) return;
    const el = document.createElement('div');
    el.className = 'orb-pulse';
    orbPulseLayer.appendChild(el);
    if (animate) animate(el, { scale: [0.72, 1.85], opacity: [0.55, 0] }, { duration: 1.7, ease: 'easeOut' });
    setTimeout(() => el.remove(), 1800);
  }
  function startPulseLoop() { stopPulseLoop(); spawnPulse(); pulseTimer = setInterval(spawnPulse, 950); }
  function stopPulseLoop() { if (pulseTimer) clearInterval(pulseTimer); pulseTimer = null; }

  /* ---------- EQ bars (speaking) ---------- */
  function startEq() {
    eqBars?.forEach((bar, i) => {
      const h = () => 0.25 + Math.random() * 0.75;
      eqAnims[i]?.stop?.();
      eqAnims[i] = animate(bar, { scaleY: [0.2, h(), h(), h(), 0.2] }, { duration: 0.9 + i * 0.13, repeat: Infinity, ease: 'easeInOut' });
    });
  }
  function stopEq() {
    eqAnims.forEach(a => a?.stop?.());
    eqAnims = [];
    eqBars?.forEach(bar => { if (!animate) bar.style.transform = 'scaleY(0.15)'; else animate(bar, { scaleY: 0.15 }, { duration: 0.3 }); });
  }

  /* ---------- chat rendering ---------- */
  function addMessage(role, text, meta) {
    if (!chatInner) return;
    const wrap = document.createElement('div');
    wrap.className = 'msg msg--' + (role === 'user' ? 'user' : role === 'note' ? 'note' : 'jarvis');

    if (role === 'note') {
      const b = document.createElement('div');
      b.className = 'bubble';
      b.textContent = text;
      wrap.appendChild(b);
    } else if (role === 'user') {
      const b = document.createElement('div');
      b.className = 'bubble';
      b.textContent = text;
      wrap.appendChild(b);
    } else {
      wrap.appendChild(Object.assign(document.createElement('div'), { className: 'msg-dot' }));
      const b = document.createElement('div');
      b.className = 'bubble';
      b.innerHTML = renderMarkdown(text);

      const metaParts = [];
      if (meta && meta.intent) {
        const cls = meta.ok === false ? 'meta-state--err' : meta.ok ? 'meta-state--ok' : '';
        metaParts.push('<span class="' + cls + '">' + esc(meta.intent) + '</span>');
      }
      if (meta && meta.note) metaParts.push('<span>' + esc(meta.note) + '</span>');
      if (meta && meta.pending) {
        activeConfirmCard = buildConfirmCard(meta.pending, b);
        b.appendChild(activeConfirmCard);
      }
      if (metaParts.length) b.innerHTML += '<div class="msg-meta">' + metaParts.join('') + '</div>';
      wrap.appendChild(b);
    }
    chatInner.appendChild(wrap);
    motionIn(wrap, { opacity: [0, 1], y: [18, 0], filter: ['blur(6px)', 'blur(0px)'] }, { duration: 0.45 });
    maybeScroll(true);
    return wrap;
  }

  function buildConfirmCard(pending, bubbleEl) {
    const card = document.createElement('div');
    card.className = 'confirm-card';
    card.innerHTML = '<div class="confirm-title">[!] confirmation required</div><div class="confirm-body">' + esc(pending.summary) + '</div><div class="confirm-actions"><button class="btn btn--ok">Confirm</button><button class="btn btn--danger">Cancel</button></div>';
    const [okBtn, cancelBtn] = card.querySelectorAll('button');
    const resolve = async approve => {
      okBtn.disabled = cancelBtn.disabled = true;
      setStatus('processing');
      try {
        const res = await api('/api/confirm', { id: pending.id, approve });
        card.style.opacity = '0.5';
        await handleResponse(res);
      } catch {
        addMessage('jarvis', 'I could not reach my backend to complete that.', { intent: 'CONNECTION_ERROR', ok: false });
        setStatus('error'); setTimeout(() => setStatus('idle'), 1500);
      }
    };
    okBtn.addEventListener('click', () => resolve(true));
    cancelBtn.addEventListener('click', () => resolve(false));
    motionIn(card, { opacity: [0, 1], y: [12, 0] }, { duration: 0.35 });
    return card;
  }

  function deactivateConfirmCards() {
    if (!activeConfirmCard) return;
    const btns = activeConfirmCard.querySelectorAll('button');
    btns.forEach(b => b.disabled = true);
    activeConfirmCard = null;
  }

  function maybeScroll(force) {
    if (!chatScroll) return;
    const near = chatScroll.scrollHeight - chatScroll.scrollTop - chatScroll.clientHeight < 140;
    if (force || near) chatScroll.scrollTo({ top: chatScroll.scrollHeight, behavior: 'smooth' });
  }

  /* ---------- activity log ---------- */
  function logActivity(opts) {
    if (!activityLog) return;
    const kind = opts.kind || 'ok';
    const title = opts.title || '';
    const detail = opts.detail || '';
    const empty = activityLog.querySelector('.activity-empty');
    if (empty) empty.remove();
    const item = document.createElement('div');
    item.className = 'activity-item';
    const iconClass = kind === 'ok' ? 'activity-icon--ok' : kind === 'err' ? 'activity-icon--err' : kind === 'warn' ? 'activity-icon--warn' : '';
    item.innerHTML = '<span class="activity-icon ' + iconClass + '"></span><div class="activity-main"><div class="activity-title">' + esc(title) + '</div>' + (detail ? '<div class="activity-detail">' + esc(detail) + '</div>' : '') + '</div><span class="activity-time">' + timeStr() + '</span>';
    activityLog.prepend(item);
    motionIn(item, { opacity: [0, 1], x: [-10, 0] }, { duration: 0.3 });
    while (activityLog.children.length > 40) activityLog.lastChild.remove();
    activityCount++;
    if (activityCountEl) activityCountEl.textContent = activityCount;
  }

  /* ---------- TTS ---------- */
  function pickVoice() {
    if (!('speechSynthesis' in window)) return;
    const voices = speechSynthesis.getVoices();
    const prefs = [/guy/i, /ryan/i, /george/i, /david/i, /mark/i, /uk english male/i, /daniel/i, /arthur/i];
    for (const p of prefs) {
      const v = voices.find(v => p.test(v.name) && v.lang.startsWith('en'));
      if (v) { ttsVoice = v; return; }
    }
    ttsVoice = voices.find(v => v.lang === 'en-GB') || voices.find(v => v.lang.startsWith('en')) || null;
  function splitForSpeech(text, maxLen) {
    maxLen = maxLen || 220;
    const sentences = text.match(/[^.!?]+[.!?]+/g) || [text];
    const chunks = [];
    let cur = '';
    for (let i = 0; i < sentences.length; i++) {
      const s = sentences[i];
      if ((cur + s).length > maxLen && cur) { chunks.push(cur.trim()); cur = s; }
      else cur += s;
    }
    if (cur.trim()) chunks.push(cur.trim());
    return chunks;
  }

  let currentAudio = null;

  function speak(text, returnTo) {
    returnTo = returnTo || 'idle';
    if (ttsMuted || !text?.trim()) { setStatus(returnTo); return; }
    stopSpeaking();
    const chunks = splitForSpeech(text, 220);
    if (!chunks.length) { setStatus(returnTo); return; }
    speaking = true;
    setStatus('speaking');
    playChunks(chunks, 0, returnTo);
  }

  function playChunks(chunks, index, returnTo) {
    if (index >= chunks.length || !speaking) { finishSpeaking(returnTo); return; }
    const chunk = chunks[index];
    fetch('/api/tts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: chunk, voice: 'en-US-GuyNeural' })
    }).then(r => r.arrayBuffer()).then(audioData => {
      if (!speaking) { finishSpeaking(returnTo); return; }
      const blob = new Blob([audioData], { type: 'audio/mpeg' });
      const url = URL.createObjectURL(blob);
      currentAudio = new Audio(url);
      currentAudio.onended = () => { URL.revokeObjectURL(url); playChunks(chunks, index + 1, returnTo); };
      currentAudio.onerror = () => { URL.revokeObjectURL(url); playChunks(chunks, index + 1, returnTo); };
      currentAudio.play().catch(() => { playChunks(chunks, index + 1, returnTo); });
    }).catch(() => { playChunks(chunks, index + 1, returnTo); });
  };
    });
  }
  function finishSpeaking(returnTo) { speaking = false; currentAudio = null; if (state === 'speaking') setStatus(returnTo); }
  function stopSpeaking() { speaking = false; if (currentAudio) { currentAudio.pause(); currentAudio = null; } if (state === 'speaking') setStatus('idle'); }

  /* ---------- Voice input (STT + level meter) ---------- */
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) {
    console.warn('[JARVIS] SpeechRecognition not supported');
  } else {
    function setupRec() {
      rec = new SR();
      rec.lang = 'en-US';
      rec.continuous = false;
      rec.interimResults = true;
      rec.maxAlternatives = 1;

      rec.onstart = () => {
        recActive = true; recFinal = '';
        setStatus('listening');
        if (micBtn) micBtn.classList.add('is-live');
        startMeter();
        if (animate && micRing) micRingAnim = animate(micRing, { opacity: [0, 0.9, 0], scale: [1, 1.25, 1.45] }, { duration: 1.6, repeat: Infinity, ease: 'easeOut' });
      };

      rec.onresult = e => {
        let interim = '';
        for (let i = e.resultIndex; i < e.results.length; i++) {
          const res = e.results[i];
          if (res.isFinal) recFinal += res[0].transcript;
          else interim += res[0].transcript;
        }
        if (interim) showLive(interim);
      };

      rec.onerror = e => {
        if (e.error === 'not-allowed' || e.error === 'service-not-allowed') {
          if (micBtn) micBtn.classList.add('is-broken');
          if (micBtn) micBtn.title = 'Microphone access blocked';
          addMessage('note', 'Microphone access is blocked. Allow it in the browser and reload.');
        }
      };

      rec.onend = async () => {
        recActive = false;
        if (micBtn) micBtn.classList.remove('is-live');
        stopMeter();
        micRingAnim?.stop?.(); micRingAnim = null;
        if (micRing) micRing.style.opacity = '0';
        hideLive();
        if (recFinal.trim()) {
          sendCommand(recFinal.trim(), { voice: true });
        } else if (state === 'listening') {
          setStatus('idle');
        }
      };
    }
    setupRec();
  }

  function showLive(text) { if (liveTx) { liveTx.textContent = text || '...'; liveTx.classList.add('is-on'); } }
  function hideLive() { if (liveTx) liveTx.classList.remove('is-on'); }

  async function startMeter() {
    try {
      micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      const src = audioCtx.createMediaStreamSource(micStream);
      analyser = audioCtx.createAnalyser();
      analyser.fftSize = 512;
      src.connect(analyser);
      const data = new Uint8Array(analyser.frequencyBinCount);
      const tick = () => {
        analyser.getByteTimeDomainData(data);
        let sum = 0;
        for (let i = 0; i < data.length; i++) { const v = (data[i] - 128) / 128; sum += v * v; }
        const rms = Math.sqrt(sum / data.length);
        const level = Math.min(1, rms * 3.2);
        if (orbCoreInner) orbCoreInner.style.setProperty('--mic', level.toFixed(3));
        meterRAF = requestAnimationFrame(tick);
      };
      tick();
    } catch {
      synthMeter();
    }
  }
  function synthMeter() {
    const t0 = performance.now();
    const tick = t => {
      const s = (t - t0) / 1000;
      const level = 0.28 + 0.22 * Math.sin(s * 2.1) + 0.14 * Math.sin(s * 4.7);
      if (orbCoreInner) orbCoreInner.style.setProperty('--mic', Math.max(0, level).toFixed(3));
      meterRAF = requestAnimationFrame(tick);
    };
    meterRAF = requestAnimationFrame(tick);
  }
  function stopMeter() {
    if (meterRAF) cancelAnimationFrame(meterRAF);
    meterRAF = 0;
    if (orbCoreInner) orbCoreInner.style.setProperty('--mic', '0');
    if (micStream) { micStream.getTracks().forEach(t => t.stop()); micStream = null; }
    if (audioCtx) { audioCtx.close(); audioCtx = null; }
  }

  function toggleListening() {
    if (!rec) { addMessage('note', 'Voice input not supported in this browser. Use Chrome or Edge.'); return; }
    if (state === 'listening' || recActive) { stopListening(); return; }
    stopSpeaking();
    recFinal = '';
    try { rec.start(); } catch {}
  }
  function stopListening(keepText) { if (!rec || !recActive) return; try { rec.stop(); } catch {} if (!keepText) recFinal = ''; }

  /* ---------- command flow ---------- */
  async function sendCommand(text, opts) {
    text = (text || '').trim();
    if (!text) return;
    stopSpeaking();
    stopListening(true);
    addMessage('user', text);
    logActivity({ kind: 'cmd', title: 'Command', detail: text });
    setStatus('processing', 'Thinking...');
    try {
      const res = await api('/api/command', { text });
      await handleResponse(res, opts);
    } catch (err) {
      console.error('sendCommand error:', err);
      const msg = 'I could not reach my backend. Make sure run.py is still running.';
      addMessage('jarvis', msg, { intent: 'CONNECTION_ERROR', ok: false });
      logActivity({ kind: 'err', title: 'Connection', detail: 'backend unreachable' });
      setStatus('error', 'Backend unreachable');
      setTimeout(() => { if (state === 'error') setStatus('idle'); }, 1800);
    }
  }

  async function handleResponse(res, opts) {
    deactivateConfirmCards();
    const execStep = (res.steps || []).find(s => s.state === 'executing');

    if (res.state === 'confirm' && res.pending) {
      addMessage('jarvis', res.reply, { intent: res.intent, pending: res.pending, note: res.note });
      logActivity({ kind: 'warn', title: 'Confirmation', detail: res.pending.summary });
      setStatus('confirm');
      speak(stripMarkdownForSpeech(res.reply).replace(/\n+/g, ' '), 'confirm');
      return;
    }

    if (execStep && res.state !== 'error') {
      setStatus('executing', execStep.message || 'Working...');
      await wait(res.state === 'done' ? 850 : 0);
    }

    addMessage('jarvis', res.reply, { intent: res.intent, ok: res.state !== 'error', note: res.note, data: res.result?.data });
    logActivity({ kind: res.state === 'error' ? 'err' : 'ok', title: res.intent || 'Response', detail: (res.reply || '').slice(0, 80).replace(/\n/g, ' ') });

    if (res.state === 'error') {
      setStatus('error', 'Something went wrong');
      await wait(900);
      speak(res.reply, 'idle');
    } else {
      speak(res.reply, 'idle');
    }

    try { const h = await api('/api/history'); memCount = (h.history || []).length; if (sysMemory) sysMemory.textContent = memCount + ' turns'; } catch {}
  }

  /* ---------- system panel / clock / llm pill ---------- */
  async function refreshSystem() {
    try {
      const s = await api('/api/status');
      if (sysUser) sysUser.textContent = s.user || '---';
      if (sysWorkspace) { sysWorkspace.textContent = shortenPath(s.workspace || ''); sysWorkspace.title = s.workspace || ''; }
      if (sysModel) sysModel.textContent = s.llm?.model || '---';
      if (sysTools) sysTools.textContent = s.tools + ' tools';
      updateLlmPill(s.llm);
      memCount = s.turns ? s.turns : (await api('/api/history')).history.length;
      if (sysMemory) sysMemory.textContent = memCount + ' turns';
    } catch {}
  }

  function updateLlmPill(llm) {
    if (!llm || !llmDot || !llmText) return;
    const map = { online: ['ok', 'AI online - ' + llm.model], ready: ['ok', 'AI ready - ' + llm.model], error: ['err', 'AI unreachable'], unconfigured: ['warn', 'Offline brain'], disabled: ['warn', 'AI disabled'] };
    const clsLabel = map[llm.state] || ['warn', 'AI: ' + llm.state];
    const cls = clsLabel[0];
    const label = clsLabel[1];
    llmDot.className = 'pill-dot pill-dot--' + cls;
    llmText.textContent = label;
    if (llm.state === 'error') llmPill.title = llm.last_error || 'The AI service could not be reached.';
    if (llm.state === 'unconfigured') llmPill.title = 'Set JARVIS_API_KEY or OPENAI_API_KEY to enable full LLM answers.';
  }

  function startClock() {
    if (clockEl) clockEl.textContent = timeStr();
    setInterval(() => { if (clockEl) clockEl.textContent = timeStr(); }, 1000);
  }

  /* ---------- chips ---------- */
  function buildChips() {
    if (!chips) return;
    CHIPS.forEach(pair => {
      const label = pair[0];
      const cmd = pair[1];
      const btn = document.createElement('button');
      btn.className = 'chip';
      btn.textContent = label;
      btn.addEventListener('click', () => sendCommand(cmd));
      chips.appendChild(btn);
    });
  }

  /* ---------- gestures ---------- */
  function attachGestures() {
    if (!hover || !press) return;
    document.querySelectorAll('.round-btn, .btn, .chip, .icon-btn').forEach(el => {
      hover(el, () => { if (animate) animate(el, { scale: 1.06, boxShadow: '0 0 24px rgba(79,214,255,0.25)' }, { duration: 0.22, ease: EASE_OUT }); return () => { if (animate) animate(el, { scale: 1, boxShadow: '0 0 0px rgba(79,214,255,0)' }, { duration: 0.3, ease: EASE_OUT }); }; });
      press(el, () => { if (animate) animate(el, { scale: 0.92 }, { duration: 0.1 }); return () => { if (animate) animate(el, { scale: 1 }, { duration: 0.25, ease: EASE_OUT }); }; });
    });
  }

  /* ---------- events ---------- */
  function wireEvents() {
    if (sendBtn) sendBtn.addEventListener('click', () => { const v = textIn?.value?.trim(); if (v) { textIn.value = ''; sendCommand(v); } });
    if (textIn) textIn.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); const v = textIn.value.trim(); if (v) { textIn.value = ''; sendCommand(v); } } if (e.key === 'Escape') { stopSpeaking(); stopListening(); setStatus('idle'); } });
    if (micBtn) micBtn.addEventListener('click', toggleListening);
    if (ttsBtn) ttsBtn.addEventListener('click', () => { ttsMuted = !ttsMuted; ttsBtn.classList.toggle('is-muted', ttsMuted); if (ttsMuted) stopSpeaking(); });
    if (resetBtn) resetBtn.addEventListener('click', async () => { try { await api('/api/reset', {}); } catch {} chatInner.innerHTML = ''; addMessage('note', 'Conversation cleared. Memory reset.'); logActivity({ kind: 'warn', title: 'Memory', detail: 'conversation cleared' }); setStatus('idle'); memCount = 0; if (sysMemory) sysMemory.textContent = '0 turns'; });

    document.addEventListener('keydown', e => { if (e.key === 'm' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); toggleListening(); } if (e.key === 'Escape') { stopSpeaking(); stopListening(); setStatus('idle'); } });

    setTimeout(() => { if (textIn) textIn.focus(); }, 100);
  }

  /* ---------- init ---------- */
  function buildTicks() {
    const g = document.getElementById('orbTicks');
    if (!g) return;
    const cx = 120, cy = 120, r1 = 112, r2 = 117;
    for (let i = 0; i < 60; i++) {
      const a = (i / 60) * Math.PI * 2;
      const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
      line.setAttribute('x1', cx + Math.cos(a) * r1);
      line.setAttribute('y1', cy + Math.sin(a) * r1);
      line.setAttribute('x2', cx + Math.cos(a) * r2);
      line.setAttribute('y2', cy + Math.sin(a) * r2);
      line.setAttribute('stroke-width', i % 5 === 0 ? 1.4 : 0.7);
      g.appendChild(line);
    }
  }

  async function init() {
    console.log('[JARVIS] init() starting');
    cacheDOM();
    if (!textIn || !sendBtn || !chatInner || !orb || !statusText) {
      console.error('[JARVIS] CRITICAL: Required elements missing');
      return;
    }
    buildTicks();
    startAmbient();
    attachGestures();
    buildChips();
    pickVoice();
    wireEvents();
    await Promise.all([refreshSystem(), api('/api/history').then(h => {
      const turns = h.history || [];
      if (!turns.length) {
        addMessage('note', 'Systems online - type a command, press Ctrl+M to talk, or try a suggestion on the right.');
      } else {
        turns.forEach((t, i) => {
          if (t.role === 'user') addMessage('user', t.text);
          else addMessage('jarvis', t.text, { intent: t.meta?.intent, ok: true, ts: t.ts ? new Date(t.ts * 1000).toLocaleTimeString() : null });
        });
        memCount = turns.filter(t => t.role === 'assistant').length;
        if (sysMemory) sysMemory.textContent = memCount + ' turns';
      }
    })]);
    startClock();
    console.log('[JARVIS] init() complete');
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();