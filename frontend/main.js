import { PipecatClient, RTVIEvent } from "@pipecat-ai/client-js";
import { DailyTransport } from "@pipecat-ai/daily-transport";

// ---------------------------------------------------------------------------
// Representatives (loaded from API)
// ---------------------------------------------------------------------------
let REPRESENTATIVES = [];

// ---------------------------------------------------------------------------
// Config (loaded from API)
// ---------------------------------------------------------------------------
let CONFIG = {
  demo_mode: true,
  voice_cloning_enabled: false,
  max_calls_per_day: 2,
  calls_remaining: 2,
  max_call_duration_secs: 300,
};

// ---------------------------------------------------------------------------
// Phone number normalization
// ---------------------------------------------------------------------------
function normalizePhone(raw) {
  const digits = raw.replace(/\D/g, "");
  if (digits.length === 11 && digits.startsWith("1")) {
    return "+" + digits;
  }
  if (digits.length === 10) {
    return "+1" + digits;
  }
  return "+" + digits;
}

// ---------------------------------------------------------------------------
// US states
// ---------------------------------------------------------------------------
const US_STATES = [
  ["AL","Alabama"],["AK","Alaska"],["AZ","Arizona"],["AR","Arkansas"],["CA","California"],
  ["CO","Colorado"],["CT","Connecticut"],["DE","Delaware"],["FL","Florida"],["GA","Georgia"],
  ["HI","Hawaii"],["ID","Idaho"],["IL","Illinois"],["IN","Indiana"],["IA","Iowa"],
  ["KS","Kansas"],["KY","Kentucky"],["LA","Louisiana"],["ME","Maine"],["MD","Maryland"],
  ["MA","Massachusetts"],["MI","Michigan"],["MN","Minnesota"],["MS","Mississippi"],["MO","Missouri"],
  ["MT","Montana"],["NE","Nebraska"],["NV","Nevada"],["NH","New Hampshire"],["NJ","New Jersey"],
  ["NM","New Mexico"],["NY","New York"],["NC","North Carolina"],["ND","North Dakota"],["OH","Ohio"],
  ["OK","Oklahoma"],["OR","Oregon"],["PA","Pennsylvania"],["RI","Rhode Island"],["SC","South Carolina"],
  ["SD","South Dakota"],["TN","Tennessee"],["TX","Texas"],["UT","Utah"],["VT","Vermont"],
  ["VA","Virginia"],["WA","Washington"],["WV","West Virginia"],["WI","Wisconsin"],["WY","Wyoming"],
];

// ---------------------------------------------------------------------------
// DOM refs
// ---------------------------------------------------------------------------
const form = document.getElementById("call-form");
const callRow = document.getElementById("call-row");
const callBtn = document.getElementById("call-btn");
const stateSelect = document.getElementById("state");
const repSelect = document.getElementById("rep");
const repPhoneDisplay = document.getElementById("rep-phone-display");
const customPhoneInput = document.getElementById("custom-phone");
const customRepName = document.getElementById("custom-rep-name");
const rightPanel = document.getElementById("right-panel");
const callStatusBar = document.getElementById("call-status-bar");
const statusText = document.getElementById("status-text");
const transcriptEl = document.getElementById("transcript");
const muteBtn = document.getElementById("mute-btn");
const hangupBtn = document.getElementById("hangup-btn");
const listenInCheckbox = document.getElementById("listen-in");
const messageEl = document.getElementById("message");
const recordBtn = document.getElementById("record-btn");
const recordStatus = document.getElementById("record-status");
const previewBtn = document.getElementById("preview-btn");
const limitPanel = document.getElementById("limit-panel");
const messageHint = document.getElementById("message-hint");

// ---------------------------------------------------------------------------
// Message mode toggle (template vs freestyle)
// ---------------------------------------------------------------------------
function getMessageMode() {
  return document.querySelector('input[name="message-mode"]:checked').value;
}

document.querySelectorAll('input[name="message-mode"]').forEach((radio) => {
  radio.addEventListener("change", () => {
    if (getMessageMode() === "template") {
      messageHint.textContent =
        "Paste a call script from an organization. [NAME], [ADDRESS], [REP], [PHONE] will be substituted automatically.";
      messageEl.placeholder =
        "Paste a call template here, e.g. 'My name is [NAME] and I am a constituent from [ADDRESS]...'";
    } else {
      messageHint.textContent =
        "Describe the issue you care about in your own words. The bot will craft an articulate message for you.";
      messageEl.placeholder =
        "e.g. 'I'm worried about cuts to public school funding and want my senator to vote against the bill'";
    }
  });
});

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
let pcClient = null;
let isMuted = true;
let previewPassed = false; // Must preview before calling

// Recording state
let mediaRecorder = null;
let recordedChunks = [];
let recognition = null;
let isRecording = false;

// Dev mode: check URL params
const urlParams = new URLSearchParams(window.location.search);
const devSecret = urlParams.get("dev") || "";
const isLocalhost = ["localhost", "127.0.0.1"].includes(window.location.hostname);
const vandev = urlParams.get("vandev") === "true" && isLocalhost;

// Show BYOPN only in dev mode
if (vandev) {
  document.getElementById("custom-phone-row").classList.remove("hidden");
}

// ---------------------------------------------------------------------------
// Load config from server
// ---------------------------------------------------------------------------
async function loadConfig() {
  try {
    const res = await fetch("/config");
    CONFIG = await res.json();
  } catch (err) {
    console.warn("Failed to load config:", err);
  }
  updateCallBtnState();
}

function updateCallBtnState() {
  if (CONFIG.calls_remaining <= 0) {
    callRow.classList.add("hidden");
    previewBtn.disabled = true;
    limitPanel.classList.remove("hidden");
    rightPanel.classList.add("hidden");
  } else if (!previewPassed) {
    callRow.classList.add("hidden");
  } else {
    callRow.classList.remove("hidden");
    callBtn.disabled = false;
    callBtn.textContent = `Call Now (${CONFIG.calls_remaining} left today)`;
  }
}

// ---------------------------------------------------------------------------
// Populate state dropdown — enabled states first, rest disabled
// ---------------------------------------------------------------------------
const ENABLED_STATES = new Set(["LA", "PA"]);

const enabledStates = US_STATES.filter(([code]) => ENABLED_STATES.has(code));
const disabledStates = US_STATES.filter(([code]) => !ENABLED_STATES.has(code));

for (const [code, name] of enabledStates) {
  const opt = document.createElement("option");
  opt.value = code;
  opt.textContent = name;
  stateSelect.appendChild(opt);
}

const disabledGroup = document.createElement("optgroup");
disabledGroup.label = "Coming soon";
for (const [code, name] of disabledStates) {
  const opt = document.createElement("option");
  opt.value = code;
  opt.textContent = name;
  opt.disabled = true;
  disabledGroup.appendChild(opt);
}
stateSelect.appendChild(disabledGroup);

// ---------------------------------------------------------------------------
// Load representatives by state
// ---------------------------------------------------------------------------
async function loadRepresentatives(state) {
  try {
    const res = await fetch(`/representatives?state=${encodeURIComponent(state)}`);
    const data = await res.json();
    REPRESENTATIVES = data.representatives || [];
  } catch (err) {
    console.warn("Failed to load representatives:", err);
    REPRESENTATIVES = [];
  }

  // Clear rep dropdown
  while (repSelect.options.length > 1) {
    repSelect.remove(1);
  }

  let currentLevel = "";
  for (const rep of REPRESENTATIVES) {
    if (rep.level !== currentLevel) {
      const group = document.createElement("optgroup");
      group.label = rep.level;
      repSelect.appendChild(group);
      currentLevel = rep.level;
    }
    const opt = document.createElement("option");
    opt.value = rep.phone;
    opt.textContent = rep.name + (rep.party ? ` (${rep.party[0]})` : "");
    opt.dataset.name = rep.name;
    repSelect.lastElementChild.appendChild(opt);
  }
}

stateSelect.addEventListener("change", () => {
  loadRepresentatives(stateSelect.value);
});

// Init
loadConfig();

// Show rep phone when selected, clear custom fields
repSelect.addEventListener("change", () => {
  repPhoneDisplay.value = repSelect.value || "";
  customPhoneInput.value = "";
  customRepName.value = "";
});
// Clear rep phone when custom phone is used
customPhoneInput.addEventListener("input", () => {
  repSelect.value = "";
  repPhoneDisplay.value = "";
});

// ---------------------------------------------------------------------------
// Recording + transcription
// ---------------------------------------------------------------------------
recordBtn.addEventListener("click", async () => {
  if (isRecording) {
    stopRecording();
    return;
  }

  const cloneVoice =
    document.querySelector('input[name="clone-voice"]:checked').value === "yes";

  if (cloneVoice) {
    if (!CONFIG.voice_cloning_enabled) {
      alert(
        "Voice cloning is temporarily disabled while we are in demo mode. " +
        "Your recording will still be transcribed into the message field. " +
        "Select 'Record speech only' to continue."
      );
      return;
    }
    const confirmed = confirm(
      "Your voice recording will be used to clone your voice for the call. " +
      "The audio file will be saved locally. Continue?"
    );
    if (!confirmed) return;
  }

  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    startRecording(stream, cloneVoice && CONFIG.voice_cloning_enabled);
  } catch (err) {
    recordStatus.textContent = "Microphone access denied.";
    console.error("Mic access error:", err);
  }
});

function startRecording(stream, saveForClone) {
  isRecording = true;
  recordedChunks = [];
  recordBtn.textContent = "Stop";
  recordBtn.classList.add("recording");
  recordStatus.textContent = "Recording... speak about the issue you care about.";

  mediaRecorder = new MediaRecorder(stream, { mimeType: "audio/webm" });
  mediaRecorder.ondataavailable = (e) => {
    if (e.data.size > 0) recordedChunks.push(e.data);
  };
  mediaRecorder.onstop = async () => {
    stream.getTracks().forEach((t) => t.stop());
    const blob = new Blob(recordedChunks, { type: "audio/webm" });

    if (saveForClone) {
      recordStatus.textContent = "Uploading recording...";
      try {
        const uploadRes = await fetch("/upload-voice", {
          method: "POST",
          body: blob,
        });
        const uploadData = await uploadRes.json();

        recordStatus.textContent = "Cloning voice...";
        const cloneRes = await fetch("/clone-voice", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ filename: uploadData.filename }),
        });
        const cloneData = await cloneRes.json();

        if (cloneData.voice_id) {
          recordStatus.textContent = `Voice cloned! ID: ${cloneData.voice_id}. Transcript added above.`;
        } else {
          recordStatus.textContent = `Recording saved. ${cloneData.error || "Clone unavailable."}. Transcript added above.`;
        }
      } catch (err) {
        console.error("Upload/clone failed:", err);
        recordStatus.textContent = "Failed to save/clone recording.";
      }
    } else {
      recordStatus.textContent = "Transcript added above.";
    }
  };
  mediaRecorder.start();

  const SpeechRecognition =
    window.SpeechRecognition || window.webkitSpeechRecognition;
  if (SpeechRecognition) {
    recognition = new SpeechRecognition();
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = "en-US";

    let finalTranscript = messageEl.value;

    recognition.onresult = (event) => {
      let interim = "";
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const t = event.results[i][0].transcript;
        if (event.results[i].isFinal) {
          finalTranscript += (finalTranscript ? " " : "") + t.trim();
        } else {
          interim += t;
        }
      }
      messageEl.value = finalTranscript + (interim ? " " + interim : "");
    };

    recognition.onerror = (e) => {
      console.warn("Speech recognition error:", e.error);
    };

    recognition.onend = () => {
      if (isRecording) {
        try { recognition.start(); } catch { /* already running */ }
      }
    };

    recognition.start();
  } else {
    recordStatus.textContent +=
      " (Live transcription not supported in this browser — audio still recording.)";
  }
}

function stopRecording() {
  isRecording = false;
  recordBtn.textContent = "Record";
  recordBtn.classList.remove("recording");

  if (mediaRecorder && mediaRecorder.state !== "inactive") {
    mediaRecorder.stop();
  }
  if (recognition) {
    recognition.onend = null;
    recognition.stop();
    recognition = null;
  }
}

// ---------------------------------------------------------------------------
// Transcript helpers
// ---------------------------------------------------------------------------
function addTranscriptLine(speaker, text, className) {
  const line = document.createElement("div");
  line.className = "transcript-line";
  line.innerHTML = `<span class="speaker ${className}">${speaker}:</span> <span class="text">${escapeHtml(text)}</span>`;
  transcriptEl.appendChild(line);
  transcriptEl.scrollTop = transcriptEl.scrollHeight;
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

function setStatus(msg) {
  statusText.textContent = msg;
}

// ---------------------------------------------------------------------------
// Audio handling — one audio element per remote participant
// ---------------------------------------------------------------------------
const audioElements = new Map();

function handleTrackStarted(track, participant) {
  if (participant?.local || track.kind !== "audio") return;

  const pid = participant?.id || track.id;
  let el = audioElements.get(pid);
  if (!el) {
    el = document.createElement("audio");
    el.autoplay = true;
    document.body.appendChild(el);
    audioElements.set(pid, el);
  }
  el.srcObject = new MediaStream([track]);
  el.play().catch(() => {});
}

function handleTrackStopped(track, participant) {
  if (participant?.local) return;

  const pid = participant?.id || track.id;
  const el = audioElements.get(pid);
  if (el) {
    el.srcObject = null;
    el.remove();
    audioElements.delete(pid);
  }
}

// ---------------------------------------------------------------------------
// Resolve which phone number to dial
// ---------------------------------------------------------------------------
function getDialTarget() {
  const custom = customPhoneInput.value.trim();
  if (custom) {
    return {
      phone: normalizePhone(custom),
      name: customRepName.value.trim() || "your representative",
      isCustom: true,
    };
  }
  if (repSelect.value) {
    return {
      phone: repSelect.value,
      name: repSelect.selectedOptions[0]?.dataset.name || "your representative",
      isCustom: false,
    };
  }
  return null;
}

// ---------------------------------------------------------------------------
// Preview — show what the bot would say (via LLM) + moderation
// ---------------------------------------------------------------------------
previewBtn.addEventListener("click", async () => {
  const name = document.getElementById("name").value.trim();
  const state = stateSelect.value;
  const phone = document.getElementById("phone").value.trim();
  const message = messageEl.value.trim();
  const mode = getMessageMode();
  const target = getDialTarget();
  const repName = target?.name || "your representative";

  rightPanel.classList.remove("hidden");
  callStatusBar.classList.add("hidden");
  transcriptEl.innerHTML = "";
  previewBtn.disabled = true;
  previewBtn.textContent = "Generating...";

  addTranscriptLine("Preview", "Generating preview...", "bot");

  try {
    const res = await fetch("/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        constituent_name: name || "Vanessa",
        constituent_state: state,
        constituent_phone_number: phone,
        rep_name: repName,
        issue_text: message,
        message_mode: mode,
      }),
    });

    const data = await res.json();
    transcriptEl.innerHTML = "";

    // Check moderation
    const mod = data.moderation || {};
    if (mod.approved === false) {
      previewPassed = false;
      addTranscriptLine("Moderation", `Message not approved: ${mod.reason || "Content policy violation."}`, "rep");
      addTranscriptLine("Moderation", "Please revise your message and try again.", "rep");
    } else {
      previewPassed = true;

      addTranscriptLine("Preview", "If voicemail:", "bot");
      addTranscriptLine("Bot", data.voicemail, "bot");

      addTranscriptLine("Preview", "If a human answers:", "bot");
      addTranscriptLine("Bot", data.human_conversation, "bot");

      if (data.calls_remaining !== undefined) {
        CONFIG.calls_remaining = data.calls_remaining;
      }
    }
  } catch (err) {
    console.error("Preview failed:", err);
    transcriptEl.innerHTML = "";
    addTranscriptLine("Preview", "Failed to generate preview: " + err.message, "bot");
    previewPassed = false;
  } finally {
    previewBtn.disabled = false;
    previewBtn.textContent = "Preview";
    updateCallBtnState();
  }
});

// ---------------------------------------------------------------------------
// Start call
// ---------------------------------------------------------------------------
form.addEventListener("submit", async (e) => {
  e.preventDefault();

  if (!previewPassed) {
    alert("Please preview your message before calling.");
    return;
  }

  const name = document.getElementById("name").value.trim();
  const state = stateSelect.value;
  const phone = document.getElementById("phone").value.trim();
  const message = messageEl.value.trim();
  const mode = getMessageMode();
  const listenIn = listenInCheckbox.checked;

  const target = getDialTarget();
  if (!target) {
    alert("Please choose a representative or enter a phone number.");
    return;
  }

  // In demo mode, warn if using custom phone without dev secret
  if (CONFIG.demo_mode && target.isCustom && !devSecret) {
    alert("In demo mode, calls are limited to listed representatives. Select one from the dropdown.");
    return;
  }

  const normalizedUserPhone = phone ? normalizePhone(phone) : "";

  callBtn.disabled = true;
  callBtn.textContent = "Calling...";
  rightPanel.classList.remove("hidden");
  callStatusBar.classList.remove("hidden");
  transcriptEl.innerHTML = "";
  setStatus("Starting call...");

  try {
    const res = await fetch("/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        createDailyRoom: true,
        dailyRoomProperties: { enable_dialout: true },
        body: {
          dialout_settings: [{ phoneNumber: target.phone }],
          constituent_name: name,
          constituent_state: state,
          constituent_phone_number: normalizedUserPhone,
          rep_name: target.name,
          issue_text: message,
          message_mode: mode,
          preview_passed: true,
          dev_secret: devSecret,
        },
      }),
    });

    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.error || `Server error: ${res.status}`);
    }

    const data = await res.json();

    // Update remaining calls
    if (data.calls_remaining !== undefined) {
      CONFIG.calls_remaining = data.calls_remaining;
    }

    // Reset preview gate for next call
    previewPassed = false;

    if (!listenIn) {
      setStatus(`Call in progress (not listening in). ${CONFIG.calls_remaining} calls remaining today.`);
      callBtn.textContent = "Call in Progress";
      updateCallBtnState();
      return;
    }

    setStatus("Connecting to call...");

    pcClient = new PipecatClient({
      transport: new DailyTransport(),
      enableMic: false,
      enableCam: false,
      callbacks: {
        onConnected: () => {
          setStatus("Connected — waiting for bot...");
        },
        onBotReady: () => {
          setStatus("Bot active — call in progress");
        },
        onBotConnected: () => {
          setStatus("Bot connected — dialing representative...");
        },
        onBotDisconnected: () => {
          setStatus("Call ended");
          updateCallBtnState();
        },
        onDisconnected: () => {
          setStatus("Disconnected");
          pcClient = null;
          updateCallBtnState();
        },
        onTrackStarted: handleTrackStarted,
        onTrackStopped: handleTrackStopped,
        onUserTranscript: (data) => {
          if (data.final) {
            addTranscriptLine("Rep", data.text, "rep");
          }
        },
        onBotOutput: (data) => {
          if (data.spoken) {
            addTranscriptLine("Bot", data.text, "bot");
          }
        },
        onError: (error) => {
          console.error("PipecatClient error:", error);
          setStatus("Error: " + (error?.data?.message || "Unknown error"));
        },
      },
    });

    await pcClient.connect({
      url: data.dailyRoom,
      token: data.dailyToken,
    });
  } catch (err) {
    console.error("Call failed:", err);
    setStatus("Failed: " + err.message);
    updateCallBtnState();
  }
});

// ---------------------------------------------------------------------------
// Mute / Unmute (barge-in)
// ---------------------------------------------------------------------------
muteBtn.addEventListener("click", () => {
  if (!pcClient) return;

  isMuted = !isMuted;
  pcClient.enableMic(!isMuted);

  muteBtn.textContent = isMuted ? "Unmute" : "Mute";
  muteBtn.classList.toggle("active", !isMuted);

  if (!isMuted) {
    addTranscriptLine("You", "(joined the call)", "user");
  }
});

// ---------------------------------------------------------------------------
// Hang up
// ---------------------------------------------------------------------------
hangupBtn.addEventListener("click", async () => {
  if (pcClient) {
    setStatus("Hanging up...");
    await pcClient.disconnect();
    pcClient = null;
  }
  updateCallBtnState();
  setStatus("Call ended");
});
