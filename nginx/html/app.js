const metricsEl = document.getElementById("metrics");
const dispMsg = document.getElementById("disp-msg");

async function fetchJson(path) {
  const r = await fetch(path);
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

function renderMetrics(data) {
  const rows = [
    ["CPU %", data.cpu_percent?.toFixed(1)],
    ["RAM %", data.mem_percent?.toFixed(1)],
    ["Load 1m", data.load_avg?.[0]?.toFixed(2)],
    ["Темп. °C", data.cpu_temp_c != null ? data.cpu_temp_c.toFixed(1) : "—"],
    ["Диск %", data.disk_percent?.toFixed(1)],
    ["Время", data.uptime_human],
  ];
  if (data.fan && typeof data.fan === "object") {
    const f = data.fan;
    let fanStr =
      f.duty_percent != null
        ? `PWM ${f.duty_percent}%`
        : f.on
          ? "вкл"
          : "выкл";
    if (f.temp_c != null) fanStr += ` (${f.temp_c}°C)`;
    rows.push(["Вентилятор", fanStr]);
  }
  metricsEl.innerHTML = "";
  for (const [k, v] of rows) {
    const dt = document.createElement("dt");
    dt.textContent = k;
    const dd = document.createElement("dd");
    dd.textContent = v;
    metricsEl.append(dt, dd);
  }
}

async function tick() {
  try {
    const s = await fetchJson("/api/status");
    renderMetrics(s);
  } catch (e) {
    metricsEl.innerHTML = "";
    const dt = document.createElement("dt");
    dt.textContent = "Ошибка";
    const dd = document.createElement("dd");
    dd.textContent = String(e.message || e);
    metricsEl.append(dt, dd);
  }
}

/** Частичное обновление состояния дисплея (merge на сервере). */
async function patchDisplay(patch) {
  dispMsg.textContent = "";
  try {
    const r = await fetch("/api/display", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    });
    const j = await r.json();
    if (!r.ok) throw new Error(j.detail || JSON.stringify(j));
    dispMsg.textContent = "Сохранено";
  } catch (e) {
    dispMsg.textContent = String(e.message || e);
  }
}

const dispText = document.getElementById("disp-text");
const dispMode = document.getElementById("disp-mode");
const dispState = document.getElementById("disp-state");
const dispRotate = document.getElementById("disp-rotate");
const dispFont = document.getElementById("disp-font");
const dispFontVal = document.getElementById("disp-font-val");

let textDebounce = null;
let fontDebounce = null;

function scheduleTextPatch() {
  clearTimeout(textDebounce);
  textDebounce = setTimeout(() => {
    patchDisplay({ text: dispText.value });
  }, 350);
}

function scheduleFontPatch() {
  const n = parseInt(dispFont.value, 10);
  dispFontVal.textContent = Number.isFinite(n) ? `${n} px` : "";
  clearTimeout(fontDebounce);
  fontDebounce = setTimeout(() => {
    if (Number.isFinite(n)) patchDisplay({ font_size: n });
  }, 180);
}

async function loadDisplay() {
  dispMsg.textContent = "";
  try {
    const d = await fetchJson("/api/display");
    dispText.value = d.text ?? "";
    if (d.mode === "status" || d.mode === "pulse") dispMode.value = d.mode;
    if (d.state === "idle" || d.state === "listening" || d.state === "responding") {
      dispState.value = d.state;
    }
    const rot = Number(d.rotate);
    if (rot === 0 || rot === 1 || rot === 2 || rot === 3) {
      dispRotate.value = String(rot);
    }
    const fs = Number(d.font_size);
    if (Number.isFinite(fs) && fs >= 8 && fs <= 48) {
      dispFont.value = String(Math.round(fs));
    }
    const n = parseInt(dispFont.value, 10);
    dispFontVal.textContent = Number.isFinite(n) ? `${n} px` : "";
  } catch (e) {
    dispMsg.textContent = String(e.message || e);
  }
}

dispText.addEventListener("input", scheduleTextPatch);
dispMode.addEventListener("change", () => patchDisplay({ mode: dispMode.value }));
dispState.addEventListener("change", () => patchDisplay({ state: dispState.value }));
dispRotate.addEventListener("change", () =>
  patchDisplay({ rotate: parseInt(dispRotate.value, 10) }),
);
dispFont.addEventListener("input", scheduleFontPatch);

tick();
setInterval(tick, 2000);
loadDisplay();
