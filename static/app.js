const $ = (id) => document.getElementById(id);

const STATUS_LABEL = {
  occupied: "In house",
  due_out: "Due out",
  dirty: "Vacant dirty",
  cleaning: "Cleaning",
  inspect: "Inspect",
  maintenance: "Maint.",
  ready: "Ready",
};

function clock(hour) {
  if (hour == null || Number.isNaN(Number(hour))) return "—";
  const h = Math.floor(hour) % 24;
  const m = Math.floor((hour - Math.floor(hour)) * 60);
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
}

function showCheckout(r) {
  return r.checkout_hour != null && (r.status === "occupied" || r.status === "due_out");
}

function showCheckin(r) {
  return r.checkin_hour != null && r.incoming_guest && r.status !== "occupied";
}

function lateOut(r, hour) {
  return showCheckout(r) && hour >= r.checkout_hour;
}

function lateIn(r, hour) {
  return showCheckin(r) && hour >= r.checkin_hour;
}

function timeChips(r, hour) {
  const chips = [];
  if (showCheckout(r)) {
    chips.push(
      `<span class="chip out${lateOut(r, hour) ? " late" : ""}">Out ${clock(r.checkout_hour)}</span>`
    );
  }
  if (showCheckin(r)) {
    chips.push(
      `<span class="chip in${lateIn(r, hour) ? " late" : ""}">In ${clock(r.checkin_hour)}</span>`
    );
  }
  return chips.length ? `<div class="when-row">${chips.join("")}</div>` : "";
}

function roomTitle(r) {
  const bits = [`Room ${r.number}`, STATUS_LABEL[r.status]];
  if (showCheckout(r)) bits.push(`checkout ${clock(r.checkout_hour)}`);
  if (showCheckin(r)) bits.push(`check-in ${clock(r.checkin_hour)} (${r.incoming_guest})`);
  if (r.guest_name) bits.push(`in-house ${r.guest_name}`);
  if (r.special_request) bits.push(r.special_request);
  return bits.join(" · ");
}

document.querySelectorAll(".tab").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((b) => b.classList.remove("on"));
    btn.classList.add("on");
    document.querySelectorAll(".view").forEach((v) => v.classList.remove("on"));
    $(`view-${btn.dataset.tab}`).classList.add("on");
  });
});

function renderKpis(k) {
  const items = [
    ["Clock", k.hotel_clock],
    ["Ready", k.ready],
    ["Dirty", k.dirty],
    ["Cleaning", k.cleaning],
    ["Inspect", k.inspect],
    ["Maint.", k.maintenance],
    ["Waiting", k.guests_waiting],
    ["Anomalies", k.anomalies],
    ["Turned today", k.ready_today],
  ];
  $("kpis").innerHTML = items
    .map(([l, v]) => `<div class="kpi"><span>${l}</span><b>${v}</b></div>`)
    .join("");
}

function renderFloors(rooms, hour) {
  const floors = [3, 2, 1];
  $("floors").innerHTML = floors
    .map((f) => {
      const cells = rooms
        .filter((r) => r.floor === f)
        .sort((a, b) => a.number.localeCompare(b.number))
        .map((r) => {
          const extra = r.vip ? " vip" : "";
          const who = r.guest_name || r.incoming_guest || r.assigned_staff_id || "—";
          return `<button class="room st-${r.status}${extra}" data-id="${r.id}" title="${roomTitle(r).replaceAll('"', "&quot;")}">
            <span class="pill ${r.status}">${STATUS_LABEL[r.status]}</span>
            <div class="num">${r.number}${r.vip ? " ★" : ""}</div>
            <div class="meta">${r.room_type} · ${who}</div>
            ${timeChips(r, hour)}
          </button>`;
        })
        .join("");
      return `<div><div class="floor-label">Floor ${f}</div><div class="rooms">${cells}</div></div>`;
    })
    .join("");

  $("floors").querySelectorAll(".room").forEach((el) => {
    el.addEventListener("click", async () => {
      const id = el.dataset.id;
      const action = el.classList.contains("st-occupied") || el.classList.contains("st-due_out")
        ? "checkout"
        : "vip";
      const path = action === "checkout" ? `/api/checkout/${id}` : `/api/vip/${id}`;
      await fetch(path, { method: "POST" });
      toast(action === "checkout" ? `${id} marked vacant dirty` : `${id} VIP flag toggled`);
    });
  });
}

function renderQueue(q) {
  if (!q.length) {
    $("queue").innerHTML = "<li>Nothing pending — rare in a hotel, enjoy it.</li>";
    return;
  }
  $("queue").innerHTML = q
    .slice(0, 10)
    .map((r) => {
      const tags = [
        r.vip ? `<span class="tag">VIP</span>` : "",
        r.special ? `<span class="tag">${r.special}</span>` : "",
        r.checkin != null ? `<span class="tag">Check-in ${clock(r.checkin)}</span>` : "",
      ].join("");
      return `<li><div><strong>${r.number}</strong> ${tags}<div class="meta">${STATUS_LABEL[r.status] || r.status}</div></div><span class="score">${r.priority.toFixed(0)}</span></li>`;
    })
    .join("");
}

function renderAnomalies(list, rooms) {
  if (!list.length) {
    $("anomalies").innerHTML = "<li>No outliers vs historical clean times.</li>";
    return;
  }
  const byId = Object.fromEntries(rooms.map((r) => [r.id, r]));
  $("anomalies").innerHTML = list
    .map((a) => {
      const n = byId[a.room_id]?.number || a.room_id;
      return `<li><span>Room ${n} · ${a.kind}</span><span class="flag">score ${a.score.toFixed(2)}</span></li>`;
    })
    .join("");
}

function renderAssign(rows) {
  if (!rows.length) {
    $("assignBody").innerHTML = `<tr><td colspan="4">Waiting for free staff + pending rooms…</td></tr>`;
    return;
  }
  $("assignBody").innerHTML = rows
    .map(
      (r) => `<tr>
        <td>${r.staff_name}<div class="meta">${r.staff_id}</div></td>
        <td>${r.room_id}</td>
        <td>${r.cost}</td>
        <td>${r.reason}</td>
      </tr>`
    )
    .join("");
}

function seniorityLabel(s) {
  return s === "senior" ? "Senior" : "Junior";
}

function renderStaffLive(staff) {
  if (!staff.length) {
    $("staffLive").innerHTML = "<li>No staff roster.</li>";
    return;
  }
  $("staffLive").innerHTML = staff
    .map((s) => {
      const work = s.busy ? `On ${s.current_room_id || "task"}` : "Idle";
      return `<li>
        <div>
          <span class="dot ${s.busy ? "on" : "off"}"></span>
          <span class="who">${s.name}</span>
          <div class="role">${s.role_label || s.role} · ${seniorityLabel(s.seniority)}</div>
        </div>
        <div class="meta">${work}<br>${s.tasks} done, ${s.avg_minutes}m avg</div>
      </li>`;
    })
    .join("");
}

function renderEvents(events) {
  if (!events || !events.length) {
    $("eventLog").innerHTML = "<li>Waiting for ops events…</li>";
    return;
  }
  $("eventLog").innerHTML = events
    .map(
      (e) => `<li>
        <span class="when">${clock(e.hour)}</span>
        <span class="kind-${e.kind}">${e.message}</span>
      </li>`
    )
    .join("");
}

function fillOverrideSelect(rooms) {
  const sel = $("overrideRoom");
  const prev = sel.value;
  const sorted = [...rooms].sort((a, b) => a.number.localeCompare(b.number));
  sel.innerHTML = sorted
    .map((r) => {
      const vip = r.vip ? " ★ VIP" : "";
      return `<option value="${r.id}">${r.number} — ${STATUS_LABEL[r.status]}${vip}</option>`;
    })
    .join("");
  if (prev && [...sel.options].some((o) => o.value === prev)) sel.value = prev;
}

function renderTasks(tasks) {
  $("taskBody").innerHTML = tasks
    .map((t) => {
      const flags = [t.delayed ? "delayed" : "", t.anomaly ? "anomaly" : ""].filter(Boolean).join(" · ") || "—";
      return `<tr>
        <td>${t.id}</td><td>${t.room_id}</td><td>${t.kind}</td>
        <td>${t.priority.toFixed(1)}</td><td>${t.eta_minutes}m</td>
        <td class="${t.delayed || t.anomaly ? "flag" : ""}">${flags}</td>
      </tr>`;
    })
    .join("");
}

function renderStaff(staff) {
  const maxMin = Math.max(40, ...staff.map((s) => s.minutes));
  $("staffCards").innerHTML = staff
    .map((s) => {
      const pct = Math.min(100, (s.minutes / maxMin) * 100);
      return `<div class="scard">
        <div style="display:flex;justify-content:space-between">
          <strong>${s.name}</strong>
          <span class="${s.busy ? "busy" : "free"}">${s.busy ? "On task" : "Free"}</span>
        </div>
        <div class="meta">${s.id} · ${s.role_label || s.role} · ${seniorityLabel(s.seniority)}</div>
        <div class="meta">${s.tasks} rooms · ${s.minutes} min · quality ${(s.quality * 100).toFixed(0)}%</div>
        <div class="bar"><i style="width:${pct}%"></i></div>
      </div>`;
    })
    .join("");
}

function renderNotices(notices) {
  $("notices").innerHTML = notices
    .map(
      (n) => `<li class="kind-${n.kind}">
        <span class="who">${n.guest_name} · ${n.room_id || ""}</span>
        <span>${n.message}</span>
        <span class="meta">${clock(n.hour)}</span>
      </li>`
    )
    .join("");
}

function toast(msg) {
  const el = $("toast");
  el.textContent = msg;
  el.classList.remove("hidden");
  setTimeout(() => el.classList.add("hidden"), 2200);
}

function movementState(r, hour, type) {
  const scheduled = type === "out" ? r.checkout_hour : r.checkin_hour;
  if (hour >= scheduled) return type === "out" ? "due now" : "waiting";
  const minutes = Math.round((scheduled - hour) * 60);
  if (minutes < 60) return `in ${minutes}m`;
  return `in ${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}

function renderMovements(rooms, hour, kpis) {
  const outs = rooms
    .filter((r) => showCheckout(r))
    .sort((a, b) => a.checkout_hour - b.checkout_hour);
  const ins = rooms
    .filter((r) => showCheckin(r))
    .sort((a, b) => a.checkin_hour - b.checkin_hour);

  const outHtml = outs.length
    ? outs
        .map((r) => {
          const late = lateOut(r, hour) ? " late" : "";
          const name = r.guest_name || "—";
          return `<li class="${late}"><span class="t">${clock(r.checkout_hour)} · ${r.number}</span><span class="who">${name}${r.status === "due_out" ? " · due out" : ""}</span><span class="movement-state">${movementState(r, hour, "out")}</span></li>`;
        })
        .join("")
    : "<li>No remaining check-outs on the board.</li>";

  const inHtml = ins.length
    ? ins
        .map((r) => {
          const late = lateIn(r, hour) ? " late" : "";
          const wait = late ? " · waiting" : "";
          return `<li class="${late}"><span class="t">${clock(r.checkin_hour)} · ${r.number}</span><span class="who">${r.incoming_guest}${wait}</span><span class="movement-state">${movementState(r, hour, "in")}</span></li>`;
        })
        .join("")
    : "<li>No expected arrivals yet.</li>";

  $("moveOut").innerHTML = outHtml;
  $("moveIn").innerHTML = inHtml;
  $("outCount").textContent = outs.length ? outs.length : "0";
  $("inCount").textContent = ins.length ? ins.length : "0";
  $("movementSummary").innerHTML = [
    ["Completed out", kpis.checkouts_today, "out"],
    ["Completed in", kpis.checkins_today, "in"],
    ["Guests waiting", kpis.guests_waiting, kpis.guests_waiting ? "alert" : ""],
  ].map(([label, value, tone]) => `<div class="movement-stat ${tone}"><strong>${value}</strong><span>${label}</span></div>`).join("");

  const nextOut = outs.find((r) => r.checkout_hour >= hour) || outs[0];
  const nextIn = ins.find((r) => r.checkin_hour >= hour) || ins[0];
  const outBit = nextOut ? `Next out ${clock(nextOut.checkout_hour)} · ${nextOut.number}` : "Next out —";
  const inBit = nextIn ? `Next in ${clock(nextIn.checkin_hour)} · ${nextIn.number}` : "Next in —";
  $("nextMoves").textContent = `${outBit} · ${inBit}`;
}

function paint(state) {
  $("clock").textContent = state.kpis.hotel_clock;
  $("dayLabel").textContent = state.day_label;
  renderKpis(state.kpis);
  renderFloors(state.rooms, state.hotel_hour);
  renderMovements(state.rooms, state.hotel_hour, state.kpis);
  fillOverrideSelect(state.rooms);
  renderQueue(state.analytics.priority_queue || []);
  renderStaffLive(state.analytics.staff || []);
  renderEvents(state.events || []);
  renderAnomalies(state.anomalies || [], state.rooms);
  renderAssign(state.assignments || []);
  renderTasks(state.tasks || []);
  renderStaff(state.analytics.staff || []);
  renderNotices(state.notices || []);
}

async function postOverride(action) {
  const id = $("overrideRoom").value;
  if (!id) {
    toast("Pick a room first");
    return;
  }
  const paths = {
    checkout: `/api/checkout/${id}`,
    vip: `/api/vip/${id}`,
    maintenance: `/api/maintenance/${id}`,
  };
  const res = await fetch(paths[action], { method: "POST" });
  const data = await res.json();
  if (!data.ok) {
    toast(data.error || "Override failed");
    return;
  }
  const labels = {
    checkout: "Force checkout sent",
    vip: "VIP flag toggled",
    maintenance: "Maintenance flagged",
  };
  toast(`${labels[action]} · ${id}`);
}

document.querySelectorAll("[data-override]").forEach((btn) => {
  btn.addEventListener("click", () => postOverride(btn.dataset.override));
});

$("ffwd").addEventListener("click", async () => {
  await fetch("/api/sim/tick", { method: "POST" });
  toast("Jumped 5 ticks (~25 hotel minutes)");
});

$("resetSim").addEventListener("click", async () => {
  await fetch("/api/sim/reset", { method: "POST" });
  toast("Simulation reset to opening picture");
});

function connect() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.onmessage = (ev) => paint(JSON.parse(ev.data));
  ws.onclose = () => setTimeout(connect, 1200);
}

fetch("/api/state")
  .then((r) => r.json())
  .then(paint)
  .finally(connect);
