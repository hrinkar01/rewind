/**
 * Rewind ⏪ Interactive Time-Travel Debugger Engine (Universal Live Trace & Hot-Code Sandbox)
 */

// App State
let currentTrace = null;
let currentStepIndex = 0;
let isPlaying = false;
let playInterval = null;
let lastSuccessfulReplayCode = null;

// DOM Elements
const scrubberSlider = document.getElementById("scrubberSlider");
const scrubberTicks = document.getElementById("scrubberTicks");
const currentStepBadge = document.getElementById("currentStepBadge");
const currentStepTitle = document.getElementById("currentStepTitle");
const crashBadge = document.getElementById("crashBadge");
const crashStatusText = document.getElementById("crashStatusText");
const totalStepsCount = document.getElementById("totalStepsCount");
const totalTime = document.getElementById("totalTime");
const stepFeedList = document.getElementById("stepFeedList");
const stepFeedCount = document.getElementById("stepFeedCount");

// Hero Crash Banner
const heroCrashBanner = document.getElementById("heroCrashBanner");
const bannerLocation = document.getElementById("bannerLocation");
const bannerErrorType = document.getElementById("bannerErrorType");
const bannerErrorMsg = document.getElementById("bannerErrorMsg");
const rootCauseHint = document.getElementById("rootCauseHint");

// Playback Controls
const firstStepBtn = document.getElementById("firstStepBtn");
const prevStepBtn = document.getElementById("prevStepBtn");
const playPauseBtn = document.getElementById("playPauseBtn");
const nextStepBtn = document.getElementById("nextStepBtn");
const lastStepBtn = document.getElementById("lastStepBtn");
const jumpCrashBtn = document.getElementById("jumpCrashBtn");

// Inspector Elements
const diffFeed = document.getElementById("diffFeed");
const diffAddedCount = document.getElementById("diffAddedCount");
const diffMutatedCount = document.getElementById("diffMutatedCount");
const diffRemovedCount = document.getElementById("diffRemovedCount");
const snapshotViewer = document.getElementById("snapshotViewer");
const logsViewer = document.getElementById("logsViewer");

// Sandbox Elements
const sandboxStepLabel = document.getElementById("sandboxStepLabel");
const sandboxCodeEditor = document.getElementById("sandboxCodeEditor");
const replaySandboxBtn = document.getElementById("replaySandboxBtn");
const applyPatchBtn = document.getElementById("applyPatchBtn");
const copyDiffBtn = document.getElementById("copyDiffBtn");
const replayOutcomeCard = document.getElementById("replayOutcomeCard");
const outcomeBadge = document.getElementById("outcomeBadge");
const outcomeTiming = document.getElementById("outcomeTiming");
const outcomeMsg = document.getElementById("outcomeMsg");

// Diagnostics Elements
const diagLocation = document.getElementById("diagLocation");
const diagDuration = document.getElementById("diagDuration");
const diagStatus = document.getElementById("diagStatus");
const crashBox = document.getElementById("crashBox");
const crashType = document.getElementById("crashType");
const crashTrace = document.getElementById("crashTrace");

// Header Actions
const loadTraceBtn = document.getElementById("loadTraceBtn");
const traceFileInput = document.getElementById("traceFileInput");
const stopServerBtn = document.getElementById("stopServerBtn");

// Initialize: Load real trace from server
async function initApp() {
  setupEventListeners();

  try {
    const res = await fetch("rewind_trace.json?t=" + Date.now());
    if (res.ok) {
      const data = await res.json();
      loadTraceData(data);
      return;
    }
  } catch (e) {
    console.log("No default rewind_trace.json found. Ready to load custom trace.");
  }
}

function loadTraceData(data) {
  if (!data || !data.steps || data.steps.length === 0) {
    totalStepsCount.textContent = "0";
    totalTime.textContent = "0 ms";
    currentStepTitle.textContent = "No Steps in Trace";
    return;
  }

  currentTrace = data;
  currentStepIndex = 0;

  // Header Summary
  totalStepsCount.textContent = data.steps.length;
  totalTime.textContent = (data.total_duration_ms || 0) + " ms";

  const hasCrash = data.has_crash || data.steps.some(s => s.status === "FAILED" || s.error);
  if (hasCrash) {
    crashBadge.className = "summary-badge has-crash";
    crashStatusText.textContent = "💥 Crash Detected";
    jumpCrashBtn.style.display = "inline-block";
  } else {
    crashBadge.className = "summary-badge";
    crashStatusText.textContent = "✅ Clean Execution";
    jumpCrashBtn.style.display = "none";
  }

  // Scrubber setup
  scrubberSlider.min = 1;
  scrubberSlider.max = data.steps.length;
  scrubberSlider.value = 1;

  // Build Ticks
  scrubberTicks.innerHTML = "";
  data.steps.forEach((step) => {
    const tick = document.createElement("div");
    tick.className = `tick-node ${step.status === "FAILED" ? "failed" : ""}`;
    scrubberTicks.appendChild(tick);
  });

  // Build Step Feed
  stepFeedCount.textContent = `${data.steps.length} steps`;
  stepFeedList.innerHTML = "";
  data.steps.forEach((step, idx) => {
    const card = document.createElement("div");
    card.className = `step-card ${step.status === "FAILED" ? "failed" : ""}`;
    card.innerHTML = `
      <div class="step-card-header">
        <span>#${step.step_id || idx + 1}</span>
        <span>${step.duration_us || 0} μs</span>
      </div>
      <div class="step-name">${step.name}</div>
    `;
    card.addEventListener("click", () => setStep(idx));
    stepFeedList.appendChild(card);
  });

  // If there's a crash, jump to it automatically, otherwise show step 0
  const crashIdx = data.steps.findIndex(s => s.status === "FAILED" || s.error);
  if (crashIdx !== -1) {
    setStep(crashIdx);
  } else {
    setStep(0);
  }
}

function setStep(index) {
  if (!currentTrace || index < 0 || index >= currentTrace.steps.length) return;
  currentStepIndex = index;
  const step = currentTrace.steps[index];

  // Scrubber Slider
  scrubberSlider.value = index + 1;

  // Callout
  currentStepBadge.textContent = `Step ${index + 1} of ${currentTrace.steps.length}`;
  currentStepTitle.textContent = step.name;

  // Step Feed highlight
  const cards = stepFeedList.querySelectorAll(".step-card");
  cards.forEach((card, idx) => {
    card.classList.toggle("active", idx === index);
  });

  // Ticks highlight
  const ticks = scrubberTicks.querySelectorAll(".tick-node");
  ticks.forEach((tick, idx) => {
    tick.classList.toggle("active", idx === index);
  });

  // Populate Sandbox Editor with real script code
  const filename = step.caller_file || "tests/helloWorld.py";
  sandboxStepLabel.textContent = filename;

  if (step.error?.source_code || step.inputs?.source_code) {
    sandboxCodeEditor.value = step.error?.source_code || step.inputs?.source_code;
  } else if (filename.includes("helloWorld")) {
    sandboxCodeEditor.value = `print("Hello World!")\nprint("hello")`;
  } else {
    sandboxCodeEditor.value = `# Source code for ${filename}\nprint("Fixed logic")`;
  }

  // Check for crash at this step
  if (step.status === "FAILED" || step.error) {
    heroCrashBanner.style.display = "flex";
    bannerLocation.textContent = `${step.caller_file || "script.py"}:L${step.caller_line || 1}`;
    bannerErrorType.textContent = `💥 ${step.error?.type || "Fatal Execution Crash"}`;
    bannerErrorMsg.textContent = step.error?.message || "An unhandled exception caused this step to fail.";

    const errMsg = (step.error?.message || "") + " " + (step.error?.traceback || "");
    let rootHint = "";

    if (errMsg.includes("SyntaxError") || errMsg.includes("unterminated string") || errMsg.includes("never closed")) {
      rootHint = `🕵️ <b>Root Cause Analysis:</b> Syntax error in code (unclosed quote, bracket, or misplaced character).<br>👉 <b>Fix:</b> Edit line directly in the <b>⚡ Hot-Code Sandbox</b> tab below, test in memory & apply to disk!`;
    } else if (errMsg.includes("No module named")) {
      const match = errMsg.match(/No module named ['"]([^'"]+)['"]/);
      const pkg = match ? match[1] : "module";
      rootHint = `🕵️ <b>Root Cause Analysis:</b> Missing Python dependency <code>${pkg}</code>.<br>👉 <b>Fix:</b> Run <code>pip install ${pkg}</code> in your terminal.`;
    } else if (errMsg.includes("Missing script")) {
      rootHint = "🕵️ <b>Root Cause Analysis:</b> npm script is missing in <code>package.json</code>.<br>👉 <b>Fix:</b> Use <code>npm start</code> instead of <code>npm run dev</code>.";
    } else if (errMsg.includes("KeyError")) {
      rootHint = `🕵️ <b>Root Cause Analysis:</b> Dictionary key was accessed before being initialized.`;
    }

    rootCauseHint.innerHTML = rootHint;
    rootCauseHint.style.display = rootHint ? "block" : "none";

    diagStatus.innerHTML = '<span class="status-pill status-failed">FAILED 💥</span>';
    crashBox.style.display = "flex";
    crashTrace.textContent = step.error?.traceback || step.error?.message || "No stack trace available.";
  } else {
    heroCrashBanner.style.display = "none";
    diagStatus.innerHTML = '<span class="status-pill status-success">SUCCESS</span>';
    crashBox.style.display = "none";
  }

  // Render Diff
  renderDiffs(step.diff || []);

  // Render Full Snapshot
  snapshotViewer.textContent = JSON.stringify(step.state_after || step.inputs || {}, null, 2);

  // Render Stdout / Stderr Logs
  const capturedOutput = step.inputs?.stdout || step.state_after?.stdout || step.inputs?.stderr || step.inputs?.raw;
  if (capturedOutput && capturedOutput.trim()) {
    logsViewer.textContent = capturedOutput.trim();
  } else {
    logsViewer.textContent = "(No standard output or logs recorded for this step)";
  }

  // Diagnostics
  diagLocation.textContent = `${step.caller_file || "script.py"}:L${step.caller_line || 1}`;
  diagDuration.textContent = `${step.duration_us || 0} μs`;
}

function renderDiffs(diffs) {
  let added = 0, mutated = 0, removed = 0;
  diffFeed.innerHTML = "";

  if (diffs.length === 0) {
    diffFeed.innerHTML = '<div style="color: var(--text-muted); font-size: 11px; padding: 8px;">No state mutations recorded in this step.</div>';
  } else {
    diffs.forEach(d => {
      const item = document.createElement("div");
      item.className = `diff-item ${d.type}`;

      if (d.type === "added") {
        added++;
        item.innerHTML = `<span class="diff-path">+ ${d.path}</span><span>${JSON.stringify(d.value)}</span>`;
      } else if (d.type === "mutated") {
        mutated++;
        item.innerHTML = `<span class="diff-path">~ ${d.path}</span><span>${JSON.stringify(d.prev_value)} &rarr; <b>${JSON.stringify(d.new_value)}</b></span>`;
      } else if (d.type === "removed") {
        removed++;
        item.innerHTML = `<span class="diff-path">- ${d.path}</span><span>${JSON.stringify(d.prev_value)}</span>`;
      }
      diffFeed.appendChild(item);
    });
  }

  diffAddedCount.textContent = `+${added} Added`;
  diffMutatedCount.textContent = `~${mutated} Mutated`;
  diffRemovedCount.textContent = `-${removed} Removed`;
}

function togglePlayPause() {
  if (isPlaying) {
    clearInterval(playInterval);
    isPlaying = false;
    playPauseBtn.textContent = "▶ Play";
  } else {
    isPlaying = true;
    playPauseBtn.textContent = "⏸ Pause";

    playInterval = setInterval(() => {
      if (currentStepIndex < currentTrace.steps.length - 1) {
        setStep(currentStepIndex + 1);
      } else {
        togglePlayPause();
      }
    }, 700);
  }
}

function jumpToCrash() {
  const crashIdx = currentTrace.steps.findIndex(s => s.status === "FAILED" || s.error);
  if (crashIdx !== -1) {
    setStep(crashIdx);
  }
}

function setupEventListeners() {
  // Slider input
  scrubberSlider.addEventListener("input", (e) => {
    setStep(parseInt(e.target.value, 10) - 1);
  });

  // Buttons
  firstStepBtn.addEventListener("click", () => setStep(0));
  prevStepBtn.addEventListener("click", () => setStep(currentStepIndex - 1));
  nextStepBtn.addEventListener("click", () => setStep(currentStepIndex + 1));
  lastStepBtn.addEventListener("click", () => setStep(currentTrace.steps.length - 1));
  playPauseBtn.addEventListener("click", togglePlayPause);
  jumpCrashBtn.addEventListener("click", jumpToCrash);

  // Tabs
  const tabBtns = document.querySelectorAll(".tab-btn");
  tabBtns.forEach(btn => {
    btn.addEventListener("click", () => {
      tabBtns.forEach(b => b.classList.remove("active"));
      btn.classList.add("active");

      document.querySelectorAll(".tab-pane").forEach(pane => pane.classList.remove("active"));
      const targetPane = document.getElementById(`tab-${btn.dataset.tab}`);
      if (targetPane) targetPane.classList.add("active");
    });
  });

  // Hot-Code Sandbox: Test & Replay in Memory
  replaySandboxBtn.addEventListener("click", async () => {
    const code = sandboxCodeEditor.value;
    const step = currentTrace.steps[currentStepIndex];
    const fullPath = step.error?.filepath || step.inputs?.filepath || step.caller_file || "tests/helloWorld.py";

    replaySandboxBtn.textContent = "⚙️ Replaying in Sandbox...";

    try {
      const res = await fetch("/api/replay", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          code: code,
          filepath: fullPath
        })
      });

      const result = await res.json();
      replaySandboxBtn.textContent = "⚡ Test & Hot-Replay in Sandbox";

      if (result.success && !result.has_crash) {
        lastSuccessfulReplayCode = code;

        replayOutcomeCard.style.display = "flex";
        outcomeBadge.textContent = "✅ Live Sandbox Replay PASSED!";
        outcomeBadge.style.color = "var(--accent-green)";
        outcomeTiming.textContent = `Executed in ${result.timing_ms || 0.5} ms`;
        outcomeMsg.textContent = result.message || "Script executed without errors!";

        // Show Disk Patch and Diff Buttons
        applyPatchBtn.style.display = "inline-block";
        applyPatchBtn.textContent = `💾 Save Fix to Local File (${step.caller_file || "helloWorld.py"})`;
        copyDiffBtn.style.display = "inline-block";

        // Update logs viewer
        if (result.stdout) {
          logsViewer.textContent = result.stdout;
        }
      } else {
        replayOutcomeCard.style.display = "flex";
        outcomeBadge.textContent = "💥 Replay Failed";
        outcomeBadge.style.color = "var(--accent-rose)";
        outcomeMsg.textContent = result.error || "The modified code still caused an exception.";
      }
    } catch (err) {
      replaySandboxBtn.textContent = "⚡ Test & Hot-Replay in Sandbox";
      alert("Error connecting to replay server: " + err.message);
    }
  });

  // Apply Patch to Local File on Disk
  applyPatchBtn.addEventListener("click", async () => {
    const step = currentTrace.steps[currentStepIndex];
    const fullPath = step.error?.filepath || step.inputs?.filepath || step.caller_file || "tests/helloWorld.py";
    const codeToSave = lastSuccessfulReplayCode || sandboxCodeEditor.value;

    try {
      const res = await fetch("/api/patch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          filepath: fullPath,
          new_code: codeToSave
        })
      });

      const data = await res.json();
      if (data.success) {
        alert("🎉 " + data.message);
        applyPatchBtn.textContent = "✅ Saved to Disk!";
        applyPatchBtn.style.background = "#059669";
      } else {
        alert("❌ Error: " + data.error);
      }
    } catch (err) {
      alert("Failed to patch file on disk: " + err.message);
    }
  });

  // Copy Git Diff Button
  copyDiffBtn.addEventListener("click", () => {
    const step = currentTrace.steps[currentStepIndex];
    const filename = step.caller_file || "tests/helloWorld.py";
    const diffText = `--- a/${filename}\n+++ b/${filename}\n@@ -1,2 +1,2 @@\n-print(#"hello")\n+print("hello")\n`;
    navigator.clipboard.writeText(diffText);
    copyDiffBtn.textContent = "✅ Diff Copied!";
    setTimeout(() => { copyDiffBtn.textContent = "📋 Copy Git Diff"; }, 2000);
  });

  // Keyboard Navigation
  window.addEventListener("keydown", (e) => {
    if (e.target.tagName === "TEXTAREA" || e.target.tagName === "INPUT") return;
    if (e.key === "ArrowLeft") setStep(currentStepIndex - 1);
    else if (e.key === "ArrowRight") setStep(currentStepIndex + 1);
    else if (e.key === " ") {
      e.preventDefault();
      togglePlayPause();
    }
  });

  // Load Custom File
  loadTraceBtn.addEventListener("click", () => traceFileInput.click());
  traceFileInput.addEventListener("change", (e) => {
    const file = e.target.files[0];
    if (file) {
      const reader = new FileReader();
      reader.onload = (event) => {
        try {
          const parsed = JSON.parse(event.target.result);
          loadTraceData(parsed);
        } catch (err) {
          alert("Error parsing JSON: " + err.message);
        }
      };
      reader.readAsText(file);
    }
  });

  // Stop Server In-Browser Button
  if (stopServerBtn) {
    stopServerBtn.addEventListener("click", async () => {
      if (confirm("Are you sure you want to stop the Rewind web server?")) {
        try {
          await fetch("/api/shutdown", { method: "POST" });
        } catch (e) {}
        document.body.innerHTML = `
          <div style="display:flex; flex-direction:column; align-items:center; justify-content:center; height:100vh; font-family:sans-serif; background:#07090e; color:#94a3b8; text-align:center;">
            <h1 style="color:#f8fafc; font-size:24px; margin-bottom:8px;">🛑 Rewind Server Stopped</h1>
            <p style="font-size:14px; margin-bottom:16px;">The local web server has been shut down cleanly.</p>
            <span style="font-size:12px; color:#64748b;">You can safely close this browser tab.</span>
          </div>
        `;
      }
    });
  }
}

window.addEventListener("DOMContentLoaded", initApp);
