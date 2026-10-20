// Chinanki reader app.

const readerEl = document.getElementById("reader");
const statusEl = document.getElementById("status");
const genBtn = document.getElementById("generate-btn");
const newInput = document.getElementById("new-count");
const lengthInput = document.getElementById("length");
const rangeInput = document.getElementById("range");
const muteInput = document.getElementById("mute");
const storiesSelect = document.getElementById("stories-select");
const topicInput = document.getElementById("topic-input");
const topicsBtn = document.getElementById("topics-btn");
const topicChipsWrap = document.getElementById("topic-chips-wrap");
const topicChips = document.getElementById("topic-chips");
const chipsClose = document.getElementById("chips-close");
const stateInfo = document.getElementById("state-info");
const pacingPauseBtn = document.getElementById("pacing-pause-btn");

const state = {
  story: null,
  words: [],
  cursor: 0,
  translationSentences: new Set(),
  wordGlossVisible: null,
  audioEnabled: true,
  pacing: {
    status: "idle",
    targetMinutes: 4,
    totalChars: 0,
    secondsPerChar: 0,
    sweepPos: 0,
    sentenceStarts: [],
    sentenceEnds: [],
    lastFrameMs: 0,
    rafId: 0,
    fadedSentences: new Set(),
  },
};

const audioEl = new Audio();
audioEl.preload = "auto";

function showStatus(msg, isError = false, ms = 2500) {
  statusEl.textContent = msg;
  statusEl.classList.toggle("error", isError);
  statusEl.classList.add("show");
  clearTimeout(showStatus._t);
  showStatus._t = setTimeout(() => statusEl.classList.remove("show"), ms);
}

// ---------------- words ----------------

function flattenWords(story) {
  const words = [];
  story.sentences.forEach((s, sIdx) => {
    s.words.forEach((w, wIdx) => {
      words.push({
        sIdx, wIdx,
        hanzi: w.hanzi,
        pinyin: w.pinyin || "",
        english: w.english || "",
        punct: !!w.punct,
      });
    });
  });
  return words;
}

// ---------------- gradient ----------------

const GRADIENT_STOPS = [
  [0.00, [58, 134, 200]],
  [0.25, [91, 168, 216]],
  [0.50, [224, 182, 74]],
  [0.75, [224, 138, 58]],
  [1.00, [200, 48, 48]],
];

function gradientColorAt(t) {
  if (t <= 0) t = 0;
  if (t >= 1) t = 1;
  for (let i = 0; i < GRADIENT_STOPS.length - 1; i++) {
    const [t0, c0] = GRADIENT_STOPS[i];
    const [t1, c1] = GRADIENT_STOPS[i + 1];
    if (t >= t0 && t <= t1) {
      const f = (t - t0) / (t1 - t0 || 1);
      const r = Math.round(c0[0] + (c1[0] - c0[0]) * f);
      const g = Math.round(c0[1] + (c1[1] - c0[1]) * f);
      const b = Math.round(c0[2] + (c1[2] - c0[2]) * f);
      return `rgb(${r}, ${g}, ${b})`;
    }
  }
  return "rgb(200, 48, 48)";
}

// ---------------- render ----------------

function buildWordRow(sent, sIdx, isOverlay) {
  const row = document.createElement("div");
  row.className = "word-row" + (isOverlay ? " overlay-row" : "");

  let lastWordCol = null;
  const nCharsInSentence = sent.words.reduce(
    (n, w) => n + (w.punct ? 0 : (w.hanzi || "").length), 0
  );
  let charCursor = 0;

  sent.words.forEach((w, wIdx) => {
    if (w.punct) {
      if (lastWordCol) {
        const suffix = document.createElement("span");
        suffix.className = "word-punct-suffix";
        suffix.textContent = w.hanzi;
        lastWordCol.appendChild(suffix);
      } else {
        const stand = document.createElement("span");
        stand.className = "word-punct-standalone";
        stand.textContent = w.hanzi;
        row.appendChild(stand);
        lastWordCol = stand;
      }
      return;
    }

    const col = document.createElement("div");
    col.className = "word-col";
    if (!isOverlay) {
      col.dataset.sIdx = sIdx;
      col.dataset.wIdx = wIdx;
    }

    const hz = document.createElement("div");
    hz.className = "word-hanzi";

    // Per-character spans
    const chars = Array.from(w.hanzi);
    for (let k = 0; k < chars.length; k++) {
      const sp = document.createElement("span");
      sp.textContent = chars[k];
      if (isOverlay) {
        // Position of this character in the sentence (0..1)
        const t = nCharsInSentence > 1
          ? (charCursor + k + 0.5) / nCharsInSentence
          : 0.5;
        sp.style.color = gradientColorAt(t);
      }
      hz.appendChild(sp);
    }
    charCursor += chars.length;

    col.appendChild(hz);

    const py = document.createElement("div");
    py.className = "word-pinyin";
    py.textContent = w.pinyin || "";
    col.appendChild(py);

    const gl = document.createElement("div");
    gl.className = "word-gloss-slot";
    gl.textContent = w.english || "";
    col.appendChild(gl);

    if (!isOverlay) {
      col.addEventListener("click", (e) => {
        e.stopPropagation();
        moveCursorTo(sIdx, wIdx);
      });
    }

    row.appendChild(col);
    lastWordCol = col;
  });

  return row;
}

function renderStory() {
  readerEl.innerHTML = "";
  if (!state.story) {
    readerEl.innerHTML = '<p class="empty">Click <strong>Generate</strong> or load a previous story from the dropdown.</p>';
    return;
  }

  const s = state.story;

  const header = document.createElement("div");
  header.className = "story-header";
  const titleEn = document.createElement("div");
  titleEn.className = "story-title-en";
  titleEn.textContent = s.title_english || s.topic || "";
  header.appendChild(titleEn);
  if (s.title_hanzi) {
    const titleHz = document.createElement("div");
    titleHz.className = "story-title-hanzi";
    titleHz.textContent = s.title_hanzi;
    header.appendChild(titleHz);
  }
  if (s.title_pinyin) {
    const titlePy = document.createElement("div");
    titlePy.className = "story-title-pinyin";
    titlePy.textContent = s.title_pinyin;
    header.appendChild(titlePy);
  }
  readerEl.appendChild(header);

  // pacing controls
  const pc = document.createElement("div");
  pc.className = "pacing-controls";

  const minInput = document.createElement("input");
  minInput.type = "number";
  minInput.min = "0";
  minInput.max = "120";
  minInput.step = "1";
  minInput.id = "pacing-minutes";
  minInput.value = String(state.pacing.targetMinutes || s.target_minutes || 4);
  pc.appendChild(minInput);

  const minLabel = document.createElement("span");
  minLabel.textContent = "min";
  pc.appendChild(minLabel);

  const startBtn = document.createElement("button");
  startBtn.id = "pacing-start";
  startBtn.className = "primary";
  startBtn.textContent = "Start";
  startBtn.addEventListener("click", () => {
    startPacing(parseInt(minInput.value, 10) || 0);
  });
  pc.appendChild(startBtn);

  const stopBtn = document.createElement("button");
  stopBtn.id = "pacing-stop";
  stopBtn.textContent = "Stop";
  stopBtn.addEventListener("click", stopPacing);
  pc.appendChild(stopBtn);

  const stateLabel = document.createElement("span");
  stateLabel.className = "pacing-state";
  stateLabel.id = "pacing-state-label";
  pc.appendChild(stateLabel);

  readerEl.appendChild(pc);

  // audio bar
  const audioBar = document.createElement("div");
  audioBar.className = "story-audio-bar";
  const playStory = document.createElement("button");
  playStory.textContent = "▶ Play full story";
  playStory.addEventListener("click", () => playStoryAudio(s.id));
  audioBar.appendChild(playStory);
  const audioHint = document.createElement("span");
  audioHint.textContent = "← → word · ↑ ↓ clause · Shift translation";
  audioBar.appendChild(audioHint);
  readerEl.appendChild(audioBar);

  // sentences
  s.sentences.forEach((sent, sIdx) => {
    const wrap = document.createElement("div");
    wrap.className = "sentence";
    wrap.dataset.sIdx = sIdx;

    const baseRow = buildWordRow(sent, sIdx, false);
    wrap.appendChild(baseRow);

    const overlayRow = buildWordRow(sent, sIdx, true);
    wrap.appendChild(overlayRow);

    const transBand = document.createElement("div");
    transBand.className = "translation-band";
    transBand.dataset.sIdx = sIdx;
    wrap.appendChild(transBand);

    wrap.addEventListener("click", (e) => {
      const c = state.words[state.cursor];
      if (!c || c.sIdx !== sIdx) {
        for (let wIdx = 0; wIdx < sent.words.length; wIdx++) {
          if (!sent.words[wIdx].punct) {
            moveCursorTo(sIdx, wIdx, false);
            break;
          }
        }
      }
      toggleSentenceTranslation(sIdx);
    });

    readerEl.appendChild(wrap);
  });

  const wl = state.story.wishlist || [];
  if (wl.length > 0) {
    const box = document.createElement("div");
    box.className = "wishlist";
    const h = document.createElement("h4");
    h.textContent = `New words you saw (${wl.length})`;
    box.appendChild(h);
    const ul = document.createElement("ul");
    wl.forEach(w => {
      const li = document.createElement("li");
      const tag = w.in_freq_list ? `rank ${w.rank}` : "not in list";
      li.textContent = `${w.hanzi} ×${w.count} · ${tag}`;
      ul.appendChild(li);
    });
    box.appendChild(ul);
    readerEl.appendChild(box);
  }

  renderCursor();
  updatePacingControlsUI();
}

// ---------------- cursor ----------------

function clearClass(cls) {
  readerEl.querySelectorAll(`.${cls}`).forEach(el => el.classList.remove(cls));
}

function renderCursor() {
  clearClass("cursor");
  clearClass("gloss-visible");

  const c = state.words[state.cursor];
  if (!c) return;

  readerEl.querySelectorAll(`.word-col[data-s-idx="${c.sIdx}"][data-w-idx="${c.wIdx}"]`)
    .forEach(el => el.classList.add("cursor"));

  const showTranslation = state.translationSentences.has(c.sIdx);
  if (!c.punct && !showTranslation) {
    const col = readerEl.querySelector(`.word-col[data-s-idx="${c.sIdx}"][data-w-idx="${c.wIdx}"]`);
    if (col) col.classList.add("gloss-visible");
  }

  const sentenceEl = readerEl.querySelector(`.sentence[data-s-idx="${c.sIdx}"]`);
  if (sentenceEl) {
    const rect = sentenceEl.getBoundingClientRect();
    const targetCenter = window.innerHeight / 2;
    const currentCenter = rect.top + rect.height / 2;
    const delta = currentCenter - targetCenter;
    if (Math.abs(delta) > 2) {
      window.scrollBy({ top: delta, behavior: "smooth" });
    }
  }

  renderSentenceTranslations();
}

function renderSentenceTranslations() {
  readerEl.querySelectorAll(".translation-band").forEach(tb => {
    const sIdx = parseInt(tb.dataset.sIdx, 10);
    if (state.translationSentences.has(sIdx)) {
      tb.textContent = state.story.sentences[sIdx].english;
    } else {
      tb.textContent = "";
    }
  });
}

function moveCursorTo(sIdx, wIdx, play = true) {
  const idx = state.words.findIndex(w => w.sIdx === sIdx && w.wIdx === wIdx);
  if (idx === -1) return;
  state.cursor = idx;
  state.wordGlossVisible = { sIdx, wIdx };
  state.translationSentences.delete(sIdx);
  renderCursor();
  if (play && !state.words[idx].punct) playWordAudio(state.words[idx].hanzi);
}

function moveCursorBy(delta) {
  if (!state.words.length) return;
  state.translationSentences.clear();
  let next = state.cursor + delta;
  let attempts = 0;
  while (next >= 0 && next < state.words.length && state.words[next].punct && attempts < 50) {
    next += delta;
    attempts++;
  }
  if (next < 0) next = 0;
  if (next >= state.words.length) next = state.words.length - 1;
  const w = state.words[next];
  moveCursorTo(w.sIdx, w.wIdx, true);
}

function moveSentenceBy(delta) {
  if (!state.story) return;
  state.translationSentences.clear();
  const c = state.words[state.cursor];
  if (!c) return;
  let targetS = c.sIdx + delta;
  if (targetS < 0) targetS = 0;
  if (targetS >= state.story.sentences.length) targetS = state.story.sentences.length - 1;
  const sent = state.story.sentences[targetS];
  for (let wIdx = 0; wIdx < sent.words.length; wIdx++) {
    if (!sent.words[wIdx].punct) {
      moveCursorTo(targetS, wIdx, true);
      return;
    }
  }
}

// ---------------- shift ----------------

function shiftAdvance() {
  if (!state.story) return;
  const c = state.words[state.cursor];
  if (!c) return;
  const sIdx = c.sIdx;

  if (!state.translationSentences.has(sIdx)) {
    state.translationSentences.add(sIdx);
    playSentenceAudio(sIdx);
    renderCursor();
    return;
  }

  const nextS = sIdx + 1;
  if (nextS >= state.story.sentences.length) return;
  const nextSent = state.story.sentences[nextS];
  for (let wIdx = 0; wIdx < nextSent.words.length; wIdx++) {
    if (!nextSent.words[wIdx].punct) {
      moveCursorTo(nextS, wIdx, false);
      break;
    }
  }
  state.translationSentences.add(nextS);
  playSentenceAudio(nextS);
  renderCursor();
}

function toggleSentenceTranslation(sIdx) {
  if (state.translationSentences.has(sIdx)) {
    state.translationSentences.delete(sIdx);
  } else {
    state.translationSentences.add(sIdx);
    playSentenceAudio(sIdx);
  }
  renderCursor();
}

// ---------------- audio ----------------

function playWordAudio(hanzi) {
  if (!state.audioEnabled || !hanzi) return;
  audioEl.pause();
  audioEl.src = `/api/audio/word/${encodeURIComponent(hanzi)}`;
  audioEl.play().catch(() => {});
}

function playSentenceAudio(sIdx) {
  if (!state.audioEnabled) return;
  if (!state.story) return;
  audioEl.pause();
  audioEl.src = `/api/audio/sentence/${state.story.id}/${sIdx}`;
  audioEl.play().catch(() => {});
}

function playStoryAudio(storyId) {
  if (!state.audioEnabled) return;
  audioEl.pause();
  audioEl.src = `/api/audio/story/${storyId}`;
  audioEl.play().catch(() => {});
}

// ---------------- pacing ----------------

function computePacingMetrics() {
  const sentences = state.story.sentences;
  const starts = [];
  const ends = [];
  let total = 0;
  for (let i = 0; i < sentences.length; i++) {
    starts.push(total);
    let chars = 0;
    for (const w of sentences[i].words) {
      if (w.punct) continue;
      chars += (w.hanzi || "").length;
    }
    total += chars;
    ends.push(total);
  }
  state.pacing.sentenceStarts = starts;
  state.pacing.sentenceEnds = ends;
  state.pacing.totalChars = total;
}

function startPacing(minutes) {
  if (!state.story) return;
  if (minutes <= 0) {
    showStatus("Set minutes > 0 to start.", true);
    return;
  }
  computePacingMetrics();
  const total = state.pacing.totalChars;
  if (total <= 0) {
    showStatus("Story has no characters to pace.", true);
    return;
  }
  state.pacing.status = "running";
  state.pacing.targetMinutes = minutes;
  state.pacing.secondsPerChar = (minutes * 60) / total;
  state.pacing.sweepPos = 0;
  state.pacing.lastFrameMs = performance.now();
  state.pacing.fadedSentences = new Set();

  clearAllClips();
  saveStoryMinutes(state.story.id, minutes);
  updatePacingControlsUI();
  pacingPauseBtn.classList.remove("hidden");
  pacingPauseBtn.textContent = "⏸";

  cancelAnimationFrame(state.pacing.rafId);
  state.pacing.rafId = requestAnimationFrame(pacingTick);
}

function pacingTick(nowMs) {
  const p = state.pacing;
  if (p.status !== "running") return;

  const dt = (nowMs - p.lastFrameMs) / 1000;
  p.lastFrameMs = nowMs;

  if (dt > 0) {
    p.sweepPos += dt / p.secondsPerChar;
  }

  // Fade any sentence just completed
  for (let i = 0; i < p.sentenceEnds.length; i++) {
    if (p.sweepPos >= p.sentenceEnds[i] && !p.fadedSentences.has(i)) {
      p.fadedSentences.add(i);
      fadeSentence(i);
    }
  }

  applyClips(p.sweepPos);
  applyEndingPulse(p.sweepPos);

  if (p.sweepPos >= p.totalChars) {
    finishPacing();
    return;
  }

  p.rafId = requestAnimationFrame(pacingTick);
}

function applyClips(sweepPos) {
  const sentences = state.story.sentences;
  const p = state.pacing;

  for (let sIdx = 0; sIdx < sentences.length; sIdx++) {
    const sentEl = readerEl.querySelector(`.sentence[data-s-idx="${sIdx}"]`);
    if (!sentEl) continue;

    // If the sentence has already begun fading, leave it alone — its overlay
    // opacity is being handled by the CSS class.
    if (p.fadedSentences.has(sIdx)) continue;

    const overlayEl = sentEl.querySelector(".overlay-row");
    if (!overlayEl) continue;

    const start = p.sentenceStarts[sIdx];
    const end = p.sentenceEnds[sIdx];
    const size = end - start;
    if (size <= 0) {
      overlayEl.style.clipPath = "inset(0 100% 0 0)";
      continue;
    }

    const local = sweepPos - start;
    let fraction;
    if (local <= 0) fraction = 0;
    else if (local >= size) fraction = 1;
    else fraction = local / size;

    // Reveal from the left: inset(right = (1 - fraction) * 100%)
    const rightPct = (1 - fraction) * 100;
    overlayEl.style.clipPath = `inset(0 ${rightPct}% 0 0)`;
  }
}

function applyEndingPulse(sweepPos) {
  const p = state.pacing;
  for (let sIdx = 0; sIdx < p.sentenceEnds.length; sIdx++) {
    const sentEl = readerEl.querySelector(`.sentence[data-s-idx="${sIdx}"]`);
    if (!sentEl) continue;
    const isCurrent = sweepPos >= p.sentenceStarts[sIdx] && sweepPos < p.sentenceEnds[sIdx];
    if (!isCurrent) {
      sentEl.classList.remove("pacing-ending");
      continue;
    }
    const size = p.sentenceEnds[sIdx] - p.sentenceStarts[sIdx];
    const local = sweepPos - p.sentenceStarts[sIdx];
    const frac = size > 0 ? local / size : 0;
    if (frac >= 0.85) {
      sentEl.classList.add("pacing-ending");
    } else {
      sentEl.classList.remove("pacing-ending");
    }
  }
}

function fadeSentence(sIdx) {
  const sentEl = readerEl.querySelector(`.sentence[data-s-idx="${sIdx}"]`);
  if (!sentEl) return;
  sentEl.classList.remove("pacing-ending");
  sentEl.classList.add("pacing-fading");
  // Reset after the fade
  setTimeout(() => {
    sentEl.classList.remove("pacing-fading");
    const overlayEl = sentEl.querySelector(".overlay-row");
    if (overlayEl) {
      overlayEl.style.clipPath = "inset(0 100% 0 0)";
      overlayEl.style.opacity = "";
    }
  }, 1600);
}

function clearAllClips() {
  readerEl.querySelectorAll(".overlay-row").forEach(ov => {
    ov.style.clipPath = "inset(0 100% 0 0)";
    ov.style.opacity = "";
  });
  readerEl.querySelectorAll(".sentence").forEach(el => {
    el.classList.remove("pacing-ending");
    el.classList.remove("pacing-fading");
  });
}

function finishPacing() {
  const p = state.pacing;
  p.status = "idle";
  cancelAnimationFrame(p.rafId);
  p.rafId = 0;
  pacingPauseBtn.classList.add("hidden");
  setTimeout(() => { clearAllClips(); }, 1600);
  updatePacingControlsUI();
}

function stopPacing() {
  const p = state.pacing;
  if (p.status === "idle") return;
  p.status = "idle";
  cancelAnimationFrame(p.rafId);
  p.rafId = 0;
  pacingPauseBtn.classList.add("hidden");
  clearAllClips();
  updatePacingControlsUI();
}

function togglePause() {
  const p = state.pacing;
  if (p.status === "running") {
    p.status = "paused";
    cancelAnimationFrame(p.rafId);
    p.rafId = 0;
    pacingPauseBtn.textContent = "▶";
    updatePacingControlsUI();
  } else if (p.status === "paused") {
    p.status = "running";
    p.lastFrameMs = performance.now();
    pacingPauseBtn.textContent = "⏸";
    state.pacing.rafId = requestAnimationFrame(pacingTick);
    updatePacingControlsUI();
  }
}

function updatePacingControlsUI() {
  const label = document.getElementById("pacing-state-label");
  const startBtn = document.getElementById("pacing-start");
  if (!label || !startBtn) return;
  const status = state.pacing.status;
  if (status === "idle") {
    label.textContent = "";
    startBtn.disabled = false;
  } else if (status === "running") {
    label.textContent = "running";
    startBtn.disabled = true;
  } else if (status === "paused") {
    label.textContent = "paused";
    startBtn.disabled = true;
  }
}

async function saveStoryMinutes(storyId, minutes) {
  try {
    await fetch(`/api/story/${storyId}/minutes`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({minutes}),
    });
    if (state.story && state.story.id === storyId) {
      state.story.target_minutes = minutes;
    }
  } catch (e) {}
}

// ---------------- story load ----------------

function setStory(rec) {
  stopPacing();

  state.story = rec;
  state.words = flattenWords(rec);
  state.cursor = 0;
  state.translationSentences = new Set();
  state.wordGlossVisible = null;
  state.pacing = {
    status: "idle",
    targetMinutes: rec.target_minutes || 0,
    totalChars: 0,
    secondsPerChar: 0,
    sweepPos: 0,
    sentenceStarts: [],
    sentenceEnds: [],
    lastFrameMs: 0,
    rafId: 0,
    fadedSentences: new Set(),
  };
  for (let i = 0; i < state.words.length; i++) {
    if (!state.words[i].punct) { state.cursor = i; break; }
  }
  renderStory();
  const c = state.words[state.cursor];
  if (c) {
    state.wordGlossVisible = { sIdx: c.sIdx, wIdx: c.wIdx };
    renderCursor();
  }
}

// ---------------- keyboard ----------------

let shiftDown = false;

document.addEventListener("keydown", (e) => {
  if (!state.story) return;
  if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;

  if (e.key === "ArrowLeft") { e.preventDefault(); moveCursorBy(-1); }
  else if (e.key === "ArrowRight") { e.preventDefault(); moveCursorBy(1); }
  else if (e.key === "ArrowUp") { e.preventDefault(); moveSentenceBy(-1); }
  else if (e.key === "ArrowDown") { e.preventDefault(); moveSentenceBy(1); }
  else if (e.key === "Shift") {
    if (!shiftDown) {
      shiftDown = true;
      shiftAdvance();
    }
    e.preventDefault();
  }
});

document.addEventListener("keyup", (e) => {
  if (e.key === "Shift") shiftDown = false;
});

// ---------------- top bar ----------------

muteInput.addEventListener("change", () => {
  state.audioEnabled = muteInput.checked;
  if (!state.audioEnabled) audioEl.pause();
});

pacingPauseBtn.addEventListener("click", togglePause);

genBtn.addEventListener("click", async () => {
  genBtn.disabled = true;
  showStatus("Generating…", false, 60000);
  try {
    const body = {
      topic: topicInput.value,
      length: parseInt(lengthInput.value, 10) || 300,
      range: parseInt(rangeInput.value, 10) || 15,
      new: parseInt(newInput.value, 10) || 10,
    };
    const r = await fetch("/api/generate", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(body),
    });
    const data = await r.json();
    if (data.ok && data.story) {
      setStory(data.story);
      showStatus("Done.");
      refreshStories();
      refreshState();
    } else {
      const errs = (data.last_errors || []).slice(0, 3).join(" · ");
      showStatus("Generation failed: " + (errs || "unknown"), true, 5000);
    }
  } catch (e) {
    showStatus("Error: " + e.message, true, 5000);
  } finally {
    genBtn.disabled = false;
  }
});

topicsBtn.addEventListener("click", async () => {
  topicsBtn.disabled = true;
  topicChips.innerHTML = "";
  showStatus("Asking for topics…", false, 30000);
  try {
    const hint = topicInput.value || "";
    const r = await fetch(`/api/topics?hint=${encodeURIComponent(hint)}`);
    const data = await r.json();
    const topics = data.topics || [];
    if (topics.length === 0) {
      showStatus("No topics returned.", true);
      topicChipsWrap.classList.add("hidden");
    } else {
      topics.forEach(t => {
        const b = document.createElement("button");
        b.textContent = t;
        b.addEventListener("click", () => {
          topicInput.value = t;
          topicChipsWrap.classList.add("hidden");
        });
        topicChips.appendChild(b);
      });
      topicChipsWrap.classList.remove("hidden");
      showStatus("Topics ready.");
    }
  } catch (e) {
    showStatus("Error: " + e.message, true);
  } finally {
    topicsBtn.disabled = false;
  }
});

chipsClose.addEventListener("click", () => {
  topicChipsWrap.classList.add("hidden");
  topicChips.innerHTML = "";
});

storiesSelect.addEventListener("change", async () => {
  const id = storiesSelect.value;
  if (!id) return;
  const r = await fetch(`/api/story/${id}`);
  if (!r.ok) { showStatus("Could not load story", true); return; }
  const rec = await r.json();
  setStory(rec);
});

async function refreshStories() {
  try {
    const r = await fetch("/api/stories");
    const data = await r.json();
    const stories = data.stories || [];
    storiesSelect.innerHTML = '<option value="">— previous stories —</option>';
    stories.forEach(s => {
      const opt = document.createElement("option");
      opt.value = s.id;
      const days = s.days_ago === 0 ? "today" : `${s.days_ago}d ago`;
      const label = s.title_english || s.title_hanzi || s.id;
      opt.textContent = `${days} · ${label}`;
      storiesSelect.appendChild(opt);
    });
  } catch (e) {}
}

async function refreshState() {
  try {
    const r = await fetch("/api/state");
    const data = await r.json();
    stateInfo.textContent = `phase ${data.phase} · pool ${data.free_bound} · introduced ${data.introduced}`;
  } catch (e) {}
}

// ---------------- init ----------------

refreshStories();
refreshState();
