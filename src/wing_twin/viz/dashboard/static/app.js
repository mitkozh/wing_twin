/* Wing Twin Dashboard — live MQTT state + CSV export + test controls */
(function () {
  "use strict";

  const POLL_MS = 500;

  const els = {
    /* header */
    statusBadge: document.getElementById("status-badge"),
    recordCount: document.getElementById("record-count"),
    /* connection */
    mqttIndicator: document.getElementById("mqtt-indicator"),
    mqttStatus: document.getElementById("mqtt-status"),
    lastMsg: document.getElementById("last-msg"),
    /* stepper */
    stepperFill: document.getElementById("stepper-fill"),
    stepperPos: document.getElementById("stepper-pos"),
    posSlider: document.getElementById("pos-slider"),
    posInput: document.getElementById("pos-input"),
    btnSet: document.getElementById("btn-set"),
    btnHome: document.getElementById("btn-home"),
    btnEnable: document.getElementById("btn-stepper-enable"),
    btnDisable: document.getElementById("btn-stepper-disable"),
    /* LED */
    ledTip: document.getElementById("led-tip"),
    ledMid: document.getElementById("led-mid"),
    ledRoot: document.getElementById("led-root"),
    btnLedApply: document.getElementById("btn-led-apply"),
    /* test controls */
    btnTare: document.getElementById("btn-tare"),
    btnReqStatus: document.getElementById("btn-request-status"),
    testFeedback: document.getElementById("test-feedback"),
    /* strain */
    strainTbody: document.getElementById("strain-tbody"),
    dummyVal: document.getElementById("dummy-val"),
    homeOffsetVal: document.getElementById("home-offset-val"),
    lastTareVal: document.getElementById("last-tare-val"),
    /* export */
    exportStart: document.getElementById("export-start"),
    exportEnd: document.getElementById("export-end"),
    btnExport: document.getElementById("btn-export"),
    btnSetRange: document.getElementById("btn-set-range"),
    exportInfo: document.getElementById("export-info"),
  };

  const CHANNEL_NAMES = [
    "root_0", "root_45", "root_90",
    "middle_0", "middle_45", "middle_90",
    "tip_0", "tip_45", "tip_90",
  ];

  function clamp(v, lo, hi) { return Math.min(Math.max(v, lo), hi); }

  function toDatetimeLocal(ts) {
    const d = new Date(ts * 1000);
    const pad = (n) => String(n).padStart(2, "0");
    return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()) +
      "T" + pad(d.getHours()) + ":" + pad(d.getMinutes()) + ":" + pad(d.getSeconds());
  }

  function fromDatetimeLocal(str) {
    if (!str) return null;
    const d = new Date(str);
    return d.getTime() / 1000;
  }

  function formatTimeSpan(sec) {
    if (!sec || sec <= 0) return "—";
    const total = Math.round(Date.now() / 1000 - sec);
    if (total < 60) return total + "s ago";
    if (total < 3600) return Math.floor(total / 60) + "m ago";
    return Math.floor(total / 3600) + "h ago";
  }

  /* ---- UI updates ---- */
  function setStepperGauge(pos) {
    const pct = clamp(((pos + 500) / (2720 + 500)) * 100, 0, 100);
    els.stepperFill.style.width = pct + "%";
    els.stepperPos.textContent = pos;
    els.posSlider.value = pos;
    els.posInput.value = pos;
  }

  function renderStrainTable(raw, offset, saturated) {
    if (!raw || raw.length < 9) return;
    const maxVal = Math.max(...raw.map(Math.abs), 1);
    let html = "";
    for (let i = 0; i < 9; i++) {
      const pct = clamp((Math.abs(raw[i]) / maxVal) * 100, 0, 100);
      const sat = saturated && saturated[i];
      const barClass = sat ? "strain-fill sat" : "strain-fill ok";
      const statusText = sat ? "SATURATED" : "ok";
      const off = (offset && offset[i] != null) ? offset[i].toFixed(2) : "—";
      html += `<tr>
        <td class="ch-name">${CHANNEL_NAMES[i]}</td>
        <td class="ch-raw">${raw[i].toLocaleString()}</td>
        <td class="ch-off">${off}</td>
        <td class="ch-bar"><div class="strain-bar"><div class="${barClass}" style="width:${pct}%"></div></div></td>
        <td class="ch-stat ${sat ? 'sat-text' : ''}">${statusText}</td>
      </tr>`;
    }
    els.strainTbody.innerHTML = html;
  }

  function setOnline(online) {
    els.statusBadge.textContent = online ? "ONLINE" : "OFFLINE";
    els.statusBadge.className = "badge " + (online ? "badge-online" : "badge-offline");
  }

  function setMqtt(connected) {
    els.mqttIndicator.className = "dot " + (connected ? "dot-green" : "dot-red");
    els.mqttStatus.textContent = connected ? "Connected" : "Disconnected";
  }

  function feedback(msg) {
    els.testFeedback.textContent = msg;
    setTimeout(function () { if (els.testFeedback.textContent === msg) els.testFeedback.textContent = "—"; }, 5000);
  }

  /* ---- polling ---- */
  async function poll() {
    try {
      const resp = await fetch("/api/state");
      if (!resp.ok) { setOnline(false); return; }
      setOnline(true);
      const s = await resp.json();

      setMqtt(s.mqtt_connected);
      els.lastMsg.textContent = s.timestamp
        ? new Date(s.timestamp).toLocaleTimeString()
        : "—";

      els.recordCount.textContent = (s.record_count || 0) + " rec";

      setStepperGauge(s.stepper_position || 0);

      /* stepper enable buttons */
      if (s.stepper_enabled === true) {
        els.btnEnable.style.display = "none";
        els.btnDisable.style.display = "";
      } else if (s.stepper_enabled === false) {
        els.btnEnable.style.display = "";
        els.btnDisable.style.display = "none";
      }

      renderStrainTable(s.raw, s.offset, s.saturated);

      els.dummyVal.textContent = s.dummy_raw != null ? s.dummy_raw.toLocaleString() : "—";
      els.homeOffsetVal.textContent = s.home_offset != null ? s.home_offset : "—";
      els.lastTareVal.textContent = s.last_tare_time
        ? formatTimeSpan(s.last_tare_time) + " (ESP ts " + (s.last_tare_esp_ts || "?") + ")"
        : "—";
    } catch {
      setOnline(false);
    }
  }

  /* ---- CSV export ---- */
  async function doExport() {
    const start = fromDatetimeLocal(els.exportStart.value);
    const end = fromDatetimeLocal(els.exportEnd.value);
    if (start == null || end == null) {
      els.exportInfo.textContent = "Please select both start and end times.";
      return;
    }
    if (start >= end) {
      els.exportInfo.textContent = "Start time must be before end time.";
      return;
    }
    const params = new URLSearchParams({ start: start, end: end });
    const url = "/api/export.csv?" + params.toString();
    els.exportInfo.textContent = "Downloading...";
    try {
      const resp = await fetch(url);
      if (!resp.ok) { throw new Error("HTTP " + resp.status); }
      const blob = await resp.blob();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "wing_strain_export.csv";
      a.click();
      URL.revokeObjectURL(a.href);
      els.exportInfo.textContent = "Downloaded " + blob.size + " bytes.";
    } catch (e) {
      els.exportInfo.textContent = "Export failed: " + e.message;
    }
  }

  /* ---- send MQTT commands ---- */
  async function sendControl(payload) {
    try {
      const resp = await fetch("/api/control", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!resp.ok) {
        const txt = await resp.text();
        feedback("Control failed: " + txt);
        return false;
      }
      return true;
    } catch (e) {
      feedback("Control error: " + e.message);
      return false;
    }
  }

  /* ---- event bindings ---- */

  /* Stepper */
  els.btnSet.addEventListener("click", function () {
    const pos = parseInt(els.posInput.value, 10);
    if (!isNaN(pos)) {
      sendControl({ position: pos }).then(function (ok) {
        if (ok) feedback("Stepper set to " + pos);
      });
    }
  });

  els.btnHome.addEventListener("click", function () {
    sendControl({ calibrate: true }).then(function (ok) {
      if (ok) feedback("Calibration started");
    });
  });

  els.posSlider.addEventListener("input", function () {
    els.posInput.value = this.value;
  });

  els.posInput.addEventListener("change", function () {
    els.posSlider.value = this.value;
  });

  els.btnEnable.addEventListener("click", function () {
    sendControl({ stepper_enable: true }).then(function (ok) {
      if (ok) feedback("Stepper enabled");
    });
  });

  els.btnDisable.addEventListener("click", function () {
    sendControl({ stepper_enable: false }).then(function (ok) {
      if (ok) feedback("Stepper disabled");
    });
  });

  /* LEDs */
  els.btnLedApply.addEventListener("click", function () {
    const leds = [els.ledTip.value, els.ledMid.value, els.ledRoot.value];
    sendControl({ leds: leds }).then(function (ok) {
      if (ok) feedback("LEDs set to " + leds.join(", "));
    });
  });

  /* Test controls */
  els.btnTare.addEventListener("click", function () {
    sendControl({ tare: true }).then(function (ok) {
      if (ok) feedback("Tare command sent");
    });
  });

  els.btnReqStatus.addEventListener("click", function () {
    sendControl({ status: true }).then(function (ok) {
      if (ok) feedback("Status requested (check ESP serial)");
    });
  });

  /* Export */
  els.btnExport.addEventListener("click", doExport);

  els.btnSetRange.addEventListener("click", function () {
    const now = Date.now() / 1000;
    els.exportEnd.value = toDatetimeLocal(now);
    els.exportStart.value = toDatetimeLocal(now - 600);
  });

  /* ---- init ---- */
  const now = Date.now() / 1000;
  els.exportEnd.value = toDatetimeLocal(now);
  els.exportStart.value = toDatetimeLocal(now - 600);

  setInterval(poll, POLL_MS);
  poll();
})();
