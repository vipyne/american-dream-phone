import { PipecatClient, RTVIEvent } from "@pipecat-ai/client-js";
import { DailyTransport } from "@pipecat-ai/daily-transport";

// ---------------------------------------------------------------------------
// Representatives (loaded from API)
// ---------------------------------------------------------------------------
let REPRESENTATIVES = [];

// ---------------------------------------------------------------------------
// Phone number normalization
// ---------------------------------------------------------------------------
function normalizePhone(raw) {
  // Strip everything except digits
  const digits = raw.replace(/\D/g, "");
  // If it already starts with 1 and is 11 digits, just prepend +
  if (digits.length === 11 && digits.startsWith("1")) {
    return "+" + digits;
  }
  // If it's 10 digits (no country code), prepend +1
  if (digits.length === 10) {
    return "+1" + digits;
  }
  // Return as-is with + prefix if it looks intentional
  return "+" + digits;
}

// ---------------------------------------------------------------------------
// DOM refs
// ---------------------------------------------------------------------------
const form = document.getElementById("call-form");
const callBtn = document.getElementById("call-btn");
const repSelect = document.getElementById("rep");
const customPhoneInput = document.getElementById("custom-phone");
const customRepName = document.getElementById("custom-rep-name");
const callPanel = document.getElementById("call-panel");
const statusText = document.getElementById("status-text");
const transcriptEl = document.getElementById("transcript");
const muteBtn = document.getElementById("mute-btn");
const hangupBtn = document.getElementById("hangup-btn");
const listenInCheckbox = document.getElementById("listen-in");
const messageEl = document.getElementById("message");
const recordBtn = document.getElementById("record-btn");
const recordStatus = document.getElementById("record-status");
const previewBtn = document.getElementById("preview-btn");

// ---------------------------------------------------------------------------
// Populate rep dropdown (from API)
// ---------------------------------------------------------------------------
async function loadRepresentatives() {
  try {
    const res = await fetch("/representatives");
    const data = await res.json();
    REPRESENTATIVES = data.representatives || [];
  } catch (err) {
    console.warn("Failed to load representatives, using empty list:", err);
    REPRESENTATIVES = [];
  }

  // Clear existing options (except the placeholder)
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
    opt.textContent = rep.name;
    opt.dataset.name = rep.name;
    repSelect.lastElementChild.appendChild(opt);
  }
}

loadRepresentatives();

// Clear custom phone when rep is selected, and vice versa
repSelect.addEventListener("change", () => {
  customPhoneInput.value = "";
  customRepName.value = "";
});
customPhoneInput.addEventListener("input", () => {
  repSelect.value = "";
});

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
let pcClient = null;
let isMuted = true;

// Recording state
let mediaRecorder = null;
let recordedChunks = [];
let recognition = null;
let isRecording = false;

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
    const confirmed = confirm(
      "Your voice recording will be used to clone your voice for the call. " +
        "The audio file will be saved locally. Continue?"
    );
    if (!confirmed) return;
  }

  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    startRecording(stream, cloneVoice);
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

  // MediaRecorder — save audio for voice cloning
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
        // 1. Upload audio
        const uploadRes = await fetch("/upload-voice", {
          method: "POST",
          body: blob,
        });
        const uploadData = await uploadRes.json();

        // 2. Clone voice
        recordStatus.textContent = "Cloning voice...";
        const cloneRes = await fetch("/clone-voice", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ filename: uploadData.filename }),
        });
        const cloneData = await cloneRes.json();

        if (cloneData.voice_id) {
          recordStatus.textContent =
            `Voice cloned! ID: ${cloneData.voice_id}. Transcript added above.`;
        } else {
          recordStatus.textContent =
            `Recording saved to ${uploadData.filename}. Clone failed: ${cloneData.error || "unknown error"}. Transcript added above.`;
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

  // SpeechRecognition — live transcription into the textarea
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
      // If we're still supposed to be recording but recognition ended, restart
      if (isRecording) {
        try {
          recognition.start();
        } catch {
          // already running
        }
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
    recognition.onend = null; // prevent restart loop
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
    };
  }
  if (repSelect.value) {
    return {
      phone: repSelect.value, // already normalized in REPRESENTATIVES
      name: repSelect.selectedOptions[0]?.dataset.name || "your representative",
    };
  }
  return null;
}

// ---------------------------------------------------------------------------
// Preview — show what the bot would say (via LLM)
// ---------------------------------------------------------------------------
previewBtn.addEventListener("click", async () => {
  const name = document.getElementById("name").value.trim();
  const address = document.getElementById("address").value.trim();
  const phone = document.getElementById("phone").value.trim();
  const message = messageEl.value.trim();
  const target = getDialTarget();
  const repName = target?.name || "your representative";

  // Show the call panel with loading state
  callPanel.classList.remove("hidden");
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
        constituent_address: address,
        constituent_phone_number: phone,
        rep_name: repName,
        issue_text: message,
      }),
    });

    const data = await res.json();
    transcriptEl.innerHTML = "";

    addTranscriptLine("Preview", "If voicemail:", "bot");
    addTranscriptLine("Bot", data.voicemail, "bot");

    addTranscriptLine("Preview", "If a human answers:", "bot");
    addTranscriptLine("Bot", data.human_conversation, "bot");
  } catch (err) {
    console.error("Preview failed:", err);
    transcriptEl.innerHTML = "";
    addTranscriptLine("Preview", "Failed to generate preview: " + err.message, "bot");
  } finally {
    previewBtn.disabled = false;
    previewBtn.textContent = "Preview";
  }
});

// ---------------------------------------------------------------------------
// Start call
// ---------------------------------------------------------------------------
form.addEventListener("submit", async (e) => {
  e.preventDefault();

  const name = document.getElementById("name").value.trim();
  const address = document.getElementById("address").value.trim();
  const phone = document.getElementById("phone").value.trim();
  const message = messageEl.value.trim();
  const listenIn = listenInCheckbox.checked;

  const target = getDialTarget();
  if (!target) {
    alert("Please choose a representative or enter a phone number.");
    return;
  }

  // Normalize the user's own phone number too
  const normalizedUserPhone = phone ? normalizePhone(phone) : "";

  // Disable form, show call panel
  callBtn.disabled = true;
  callBtn.textContent = "Calling...";
  callPanel.classList.remove("hidden");
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
          constituent_address: address,
          constituent_phone_number: normalizedUserPhone,
          rep_name: target.name,
          issue_text: message,
        },
      }),
    });

    if (!res.ok) {
      throw new Error(`Server error: ${res.status}`);
    }

    const data = await res.json();

    if (!listenIn) {
      setStatus("Call in progress (not listening in)");
      callBtn.textContent = "Call in Progress";
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
          callBtn.disabled = false;
          callBtn.textContent = "Call Now";
        },
        onDisconnected: () => {
          setStatus("Disconnected");
          callBtn.disabled = false;
          callBtn.textContent = "Call Now";
          pcClient = null;
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
    callBtn.disabled = false;
    callBtn.textContent = "Call Now";
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
  callBtn.disabled = false;
  callBtn.textContent = "Call Now";
  setStatus("Call ended");
});
