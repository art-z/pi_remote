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

document.getElementById("btn-apply").addEventListener("click", async () => {
  dispMsg.textContent = "";
  const body = {
    text: document.getElementById("disp-text").value,
    mode: document.getElementById("disp-mode").value,
    state: document.getElementById("disp-state").value,
  };
  try {
    const r = await fetch("/api/display", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const j = await r.json();
    if (!r.ok) throw new Error(j.detail || JSON.stringify(j));
    dispMsg.textContent = "Сохранено";
  } catch (e) {
    dispMsg.textContent = String(e.message || e);
  }
});

tick();
setInterval(tick, 2000);
