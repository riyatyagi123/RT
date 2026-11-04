/* Doctor week calendar (Teams-style).
 *
 * - Shows one week: working hours, booked appointments and blocked time.
 * - Drag across empty time (or tap it) to block it; "Block time" for leave.
 * - Click an appointment for its details (and to cancel it).
 * - Click a blocked period to see it or remove it.
 *
 * All times are the clinic's local wall-clock times ("YYYY-MM-DDTHH:MM"),
 * exactly as the server stores slots, so nothing is shifted by time zones.
 */
(function () {
  "use strict";

  var root = document.getElementById("doc-cal");
  if (!root) return;

  var URLS = {
    events: root.dataset.eventsUrl,
    absences: root.dataset.absencesUrl,
    cancelBase: root.dataset.cancelBase, // ends with /0/cancel
  };
  var HOUR_PX = 72;
  var STEP = 30; // minutes per grid row
  var DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

  var els = {
    title: root.querySelector("[data-cal-title]"),
    head: root.querySelector("[data-cal-head]"),
    body: root.querySelector("[data-cal-body]"),
    status: root.querySelector("[data-cal-status]"),
    dialog: document.getElementById("cal-dialog"),
    toast: document.getElementById("cal-toast"),
  };

  var state = { weekStart: null, data: null, from: 8 * 60, to: 18 * 60, now: new Date(), synced: false };

  // ------------------------------------------------------------------ date helpers
  function pad(n) { return (n < 10 ? "0" : "") + n; }
  function ymd(d) { return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()); }
  function isoLocal(d) { return ymd(d) + "T" + pad(d.getHours()) + ":" + pad(d.getMinutes()); }
  function parseLocal(s) {
    var m = /^(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2}))?/.exec(s);
    return new Date(+m[1], +m[2] - 1, +m[3], m[4] ? +m[4] : 0, m[5] ? +m[5] : 0);
  }
  function addDays(d, n) { var c = new Date(d); c.setDate(c.getDate() + n); return c; }
  function addMinutes(d, n) { return new Date(d.getTime() + n * 60000); }
  function startOfDay(d) { return new Date(d.getFullYear(), d.getMonth(), d.getDate()); }
  function mondayOf(d) { var s = startOfDay(d); return addDays(s, -((s.getDay() + 6) % 7)); }
  function sameDay(a, b) { return ymd(a) === ymd(b); }
  function minutesOf(d) { return d.getHours() * 60 + d.getMinutes(); }
  function hm(min) { return pad(Math.floor(min / 60)) + ":" + pad(min % 60); }
  function fmtTime(d) {
    var h = d.getHours(), m = d.getMinutes();
    var suffix = h < 12 ? "AM" : "PM";
    h = h % 12 || 12;
    return h + ":" + pad(m) + " " + suffix;
  }
  function fmtDate(d) { return DAY_NAMES[(d.getDay() + 6) % 7] + " " + d.getDate() + " " + MONTHS[d.getMonth()]; }
  function fmtRange(start, end) {
    var allDay = minutesOf(start) === 0 && minutesOf(end) === 0;
    if (allDay) {
      var last = addDays(end, -1);
      return sameDay(start, last) ? fmtDate(start) + " (all day)" : fmtDate(start) + " – " + fmtDate(last) + " (all day)";
    }
    if (sameDay(start, end)) return fmtDate(start) + ", " + fmtTime(start) + " – " + fmtTime(end);
    return fmtDate(start) + ", " + fmtTime(start) + " – " + fmtDate(end) + ", " + fmtTime(end);
  }

  function csrf() { return document.querySelector("meta[name=csrf-token]").content; }
  function api(method, url, body) {
    return fetch(url, {
      method: method,
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
      body: body ? JSON.stringify(body) : undefined,
    }).then(function (res) {
      return res.json().catch(function () { return {}; }).then(function (data) {
        return { ok: res.ok, status: res.status, data: data };
      });
    });
  }

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  var toastTimer = null;
  function toast(msg) {
    els.toast.textContent = msg;
    els.toast.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { els.toast.hidden = true; }, 3500);
  }

  // ------------------------------------------------------------------ loading
  function load() {
    els.status.textContent = "Loading…";
    return fetch(URLS.events + "?start=" + ymd(state.weekStart) + "&days=7")
      .then(function (r) { return r.json(); })
      .then(function (data) {
        state.now = data.now ? parseLocal(data.now) : new Date();
        // First load: open on the clinic's (server's) current week, which can
        // differ from the browser's if the two clocks are in different zones.
        if (!state.synced) {
          state.synced = true;
          if (ymd(mondayOf(state.now)) !== ymd(state.weekStart)) { state.weekStart = mondayOf(state.now); return load(); }
        }
        state.data = data;
        computeVisibleHours();
        render();
        els.status.textContent = "";
      })
      .catch(function (err) {
        if (window.console) console.error("Calendar failed to load:", err);
        els.status.textContent = "Couldn't load the calendar. Check your connection.";
      });
  }

  function computeVisibleHours() {
    var from = 24 * 60, to = 0, d = state.data;
    d.working_hours.forEach(function (w) {
      var s = +w.start.slice(0, 2) * 60 + +w.start.slice(3);
      var e = +w.end.slice(0, 2) * 60 + +w.end.slice(3);
      from = Math.min(from, s); to = Math.max(to, e);
    });
    d.appointments.forEach(function (a) {
      var s = parseLocal(a.start), e = parseLocal(a.end);
      from = Math.min(from, minutesOf(s));
      to = Math.max(to, sameDay(s, e) ? minutesOf(e) : 24 * 60);
    });
    if (from >= to) { from = 9 * 60; to = 17 * 60; }
    state.from = Math.max(0, Math.floor(from / 60) * 60 - 60);
    state.to = Math.min(24 * 60, Math.ceil(to / 60) * 60 + 60);
  }

  // ------------------------------------------------------------------ rendering
  function render() {
    var d = state.data, ws = state.weekStart, we = addDays(ws, 6);
    els.title.textContent =
      ws.getMonth() === we.getMonth()
        ? ws.getDate() + " – " + we.getDate() + " " + MONTHS[we.getMonth()] + " " + we.getFullYear()
        : ws.getDate() + " " + MONTHS[ws.getMonth()] + " – " + we.getDate() + " " + MONTHS[we.getMonth()] + " " + we.getFullYear();

    // header
    els.head.innerHTML = "";
    els.head.appendChild(el("div", "cal-corner"));
    for (var i = 0; i < 7; i++) {
      var day = addDays(ws, i);
      var h = el("div", "cal-dayhead" + (sameDay(day, state.now) ? " is-today" : ""));
      h.appendChild(el("span", "cal-dayname", DAY_NAMES[i]));
      h.appendChild(el("span", "cal-daynum", String(day.getDate())));
      els.head.appendChild(h);
    }

    // body
    var height = ((state.to - state.from) / 60) * HOUR_PX;
    els.body.innerHTML = "";
    els.body.style.setProperty("--cal-height", height + "px");
    var gutter = el("div", "cal-gutter");
    for (var m = state.from; m < state.to; m += 60) {
      var lab = el("div", "cal-hour", fmtTime(new Date(2000, 0, 1, m / 60, 0)).replace(":00", ""));
      lab.style.top = ((m - state.from) / 60) * HOUR_PX + "px";
      gutter.appendChild(lab);
    }
    els.body.appendChild(gutter);

    for (var c = 0; c < 7; c++) els.body.appendChild(renderDay(addDays(ws, c), height));
    var empty = d.appointments.length === 0 && d.absences.length === 0;
    els.status.textContent = empty ? "No appointments or blocked time this week." : "";
  }

  function topFor(min) { return ((min - state.from) / 60) * HOUR_PX; }

  function renderDay(day, height) {
    var d = state.data;
    var col = el("div", "cal-col");
    col.dataset.date = ymd(day);
    col.style.height = height + "px";
    if (day < startOfDay(state.now)) col.classList.add("is-past");
    if (sameDay(day, state.now)) col.classList.add("is-today");

    var weekday = (day.getDay() + 6) % 7;
    d.working_hours.forEach(function (w) {
      if (w.day_of_week !== weekday) return;
      var s = +w.start.slice(0, 2) * 60 + +w.start.slice(3);
      var e = +w.end.slice(0, 2) * 60 + +w.end.slice(3);
      var band = el("div", "cal-work");
      band.style.top = topFor(Math.max(s, state.from)) + "px";
      band.style.height = topFor(Math.min(e, state.to)) - topFor(Math.max(s, state.from)) + "px";
      col.appendChild(band);
    });

    var dayStart = startOfDay(day), dayEnd = addDays(dayStart, 1);
    d.absences.forEach(function (b) {
      var s = parseLocal(b.start), e = parseLocal(b.end);
      if (e <= dayStart || s >= dayEnd) return;
      var from = Math.max(s <= dayStart ? 0 : minutesOf(s), state.from);
      var to = Math.min(e >= dayEnd ? 24 * 60 : minutesOf(e), state.to);
      if (to <= from) return;
      var block = el("button", "cal-event cal-block");
      block.type = "button";
      block.style.top = topFor(from) + "px";
      var blockH = Math.max(topFor(to) - topFor(from), 18);
      block.style.height = blockH + "px";
      if (blockH < 32) block.classList.add("cal-event-compact");
      block.appendChild(el("span", "cal-event-title", b.reason ? "Blocked · " + b.reason : "Blocked"));
      block.appendChild(el("span", "cal-event-time", s <= dayStart && e >= dayEnd ? "All day" : fmtTime(addMinutes(dayStart, from)) + " – " + fmtTime(addMinutes(dayStart, to))));
      block.setAttribute("aria-label", "Blocked time, " + fmtRange(s, e) + (b.reason ? ", " + b.reason : ""));
      block.addEventListener("click", function (ev) { ev.stopPropagation(); showBlock(b); });
      col.appendChild(block);
    });

    d.appointments.forEach(function (a) {
      var s = parseLocal(a.start), e = parseLocal(a.end);
      if (!sameDay(s, day)) return;
      var from = Math.max(minutesOf(s), state.from);
      var to = Math.min(sameDay(s, e) ? minutesOf(e) : 24 * 60, state.to);
      var card = el("button", "cal-event cal-appt cal-appt-" + a.status);
      card.type = "button";
      card.style.top = topFor(from) + "px";
      var cardH = Math.max(topFor(to) - topFor(from) - 2, 20);
      card.style.height = cardH + "px";
      var compact = cardH < 32;
      if (compact) card.classList.add("cal-event-compact");
      card.appendChild(el("span", "cal-event-title", a.patient_name));
      // Short cards show the start time only, so the patient's name fits.
      card.appendChild(el("span", "cal-event-time", compact ? fmtTime(s) : fmtTime(s) + " – " + fmtTime(e)));
      card.setAttribute("aria-label", "Appointment with " + a.patient_name + ", " + fmtRange(s, e));
      card.addEventListener("click", function (ev) { ev.stopPropagation(); showAppointment(a); });
      col.appendChild(card);
    });

    if (sameDay(day, state.now)) {
      var nm = minutesOf(state.now);
      if (nm >= state.from && nm <= state.to) {
        var line = el("div", "cal-now");
        line.style.top = topFor(nm) + "px";
        col.appendChild(line);
      }
    }

    attachSelection(col, day);
    return col;
  }

  // ------------------------------------------------------------------ drag to block
  function attachSelection(col, day) {
    var sel = null;

    function minuteAt(clientY) {
      var rect = col.getBoundingClientRect();
      var m = state.from + ((clientY - rect.top) / HOUR_PX) * 60;
      return Math.min(Math.max(Math.floor(m / STEP) * STEP, state.from), state.to - STEP);
    }
    function paint() {
      var a = Math.min(sel.anchor, sel.current), b = Math.max(sel.anchor, sel.current) + STEP;
      sel.ghost.style.top = topFor(a) + "px";
      sel.ghost.style.height = topFor(b) - topFor(a) + "px";
      sel.ghost.textContent = fmtTime(addMinutes(startOfDay(day), a)) + " – " + fmtTime(addMinutes(startOfDay(day), b));
      return [a, b];
    }

    col.addEventListener("pointerdown", function (ev) {
      if (ev.button !== 0 || ev.target.closest(".cal-event")) return;
      var m = minuteAt(ev.clientY);
      sel = { anchor: m, current: m, ghost: el("div", "cal-ghost"), touch: ev.pointerType === "touch", moved: false };
      col.appendChild(sel.ghost);
      paint();
      if (!sel.touch) { col.setPointerCapture(ev.pointerId); ev.preventDefault(); }
    });
    col.addEventListener("pointermove", function (ev) {
      if (!sel || sel.touch) return;
      var m = minuteAt(ev.clientY);
      if (m !== sel.current) { sel.current = m; sel.moved = true; paint(); }
    });
    function finish(cancelled) {
      if (!sel) return;
      var range = paint();
      sel.ghost.remove();
      sel = null;
      if (cancelled) return;
      var start = addMinutes(startOfDay(day), range[0]);
      var end = addMinutes(startOfDay(day), range[1]);
      if (end <= state.now) { toast("That time has already passed."); return; }
      openBlockForm({ start: start, end: end, allDay: false });
    }
    col.addEventListener("pointerup", function () { finish(false); });
    col.addEventListener("pointercancel", function () { finish(true); });
  }

  // ------------------------------------------------------------------ dialog helpers
  function openDialog(title, buildBody) {
    var dlg = els.dialog;
    dlg.querySelector("[data-dlg-title]").textContent = title;
    var body = dlg.querySelector("[data-dlg-body]");
    var actions = dlg.querySelector("[data-dlg-actions]");
    body.innerHTML = ""; actions.innerHTML = "";
    buildBody(body, actions);
    if (!dlg.open) dlg.showModal();
  }
  function closeDialog() { if (els.dialog.open) els.dialog.close(); }
  function button(text, cls, onClick) {
    var b = el("button", cls, text);
    b.type = "button";
    b.addEventListener("click", onClick);
    return b;
  }
  function detailRow(parent, label, value, node) {
    var row = el("div", "cal-detail");
    row.appendChild(el("dt", null, label));
    var dd = el("dd");
    if (node) dd.appendChild(node); else dd.textContent = value;
    row.appendChild(dd);
    parent.appendChild(row);
  }

  // ------------------------------------------------------------------ appointment details
  function showAppointment(a) {
    var s = parseLocal(a.start), e = parseLocal(a.end);
    openDialog(a.patient_name, function (body, actions) {
      var dl = el("dl", "cal-details");
      detailRow(dl, "Date", fmtDate(s) + " " + s.getFullYear());
      detailRow(dl, "Time", fmtTime(s) + " – " + fmtTime(e) + " (" + Math.round((e - s) / 60000) + " min)");
      detailRow(dl, "Status", null, el("span", "status-badge status-" + a.status, a.status));
      var mail = el("a", null, a.patient_email);
      mail.href = "mailto:" + a.patient_email;
      detailRow(dl, "Patient email", null, mail);
      detailRow(dl, "Notes", a.notes || "No notes from the patient.");
      if (a.booked_on) detailRow(dl, "Booked on", a.booked_on);
      body.appendChild(dl);

      var err = el("p", "cal-error"); err.hidden = true; body.appendChild(err);
      actions.appendChild(button("Close", "cal-btn", closeDialog));
      if (a.can_cancel) {
        var armed = false;
        var cancelBtn = button("Cancel appointment", "cal-btn cal-btn-danger", function () {
          if (!armed) { armed = true; cancelBtn.textContent = "Yes, cancel it"; return; }
          cancelBtn.disabled = true;
          api("POST", URLS.cancelBase.replace("/0/", "/" + a.id + "/")).then(function (res) {
            if (!res.ok) { err.textContent = res.data.error || "Couldn't cancel."; err.hidden = false; cancelBtn.disabled = false; return; }
            closeDialog(); toast("Appointment with " + a.patient_name + " cancelled."); load();
          });
        });
        actions.appendChild(cancelBtn);
      }
    });
  }

  // ------------------------------------------------------------------ blocked-time details
  function showBlock(b) {
    var s = parseLocal(b.start), e = parseLocal(b.end);
    openDialog("Blocked time", function (body, actions) {
      var dl = el("dl", "cal-details");
      detailRow(dl, "When", fmtRange(s, e));
      detailRow(dl, "Reason", b.reason || "—");
      body.appendChild(dl);
      body.appendChild(el("p", "cal-hint", "Patients and the AI assistant can't book during this time."));
      var err = el("p", "cal-error"); err.hidden = true; body.appendChild(err);
      actions.appendChild(button("Close", "cal-btn", closeDialog));
      var rm = button("Remove block", "cal-btn cal-btn-danger", function () {
        rm.disabled = true;
        api("DELETE", URLS.absences + "/" + b.id).then(function (res) {
          if (!res.ok) { err.textContent = res.data.error || "Couldn't remove it."; err.hidden = false; rm.disabled = false; return; }
          closeDialog(); toast("Blocked time removed. Those slots are bookable again."); load();
        });
      });
      actions.appendChild(rm);
    });
  }

  // ------------------------------------------------------------------ block form
  function timeSelect(value) {
    var s = el("select");
    for (var m = 0; m < 24 * 60; m += STEP) {
      var o = el("option", null, fmtTime(new Date(2000, 0, 1, m / 60, m % 60)));
      o.value = hm(m);
      s.appendChild(o);
    }
    var end = el("option", null, "12:00 AM (midnight)"); end.value = "24:00"; s.appendChild(end);
    s.value = value;
    return s;
  }

  function openBlockForm(preset) {
    openDialog("Block time", function (body, actions) {
      var form = el("form", "cal-form");
      form.noValidate = true;

      function field(label, input) {
        var w = el("label", "cal-field");
        w.appendChild(el("span", null, label));
        w.appendChild(input);
        return w;
      }
      var startDate = el("input"); startDate.type = "date"; startDate.value = ymd(preset.start);
      var endDay = preset.allDay ? addDays(preset.end, -1) : (minutesOf(preset.end) === 0 ? addDays(preset.end, -1) : preset.end);
      var endDate = el("input"); endDate.type = "date"; endDate.value = ymd(endDay);
      var startTime = timeSelect(hm(minutesOf(preset.start)));
      var endTime = timeSelect(minutesOf(preset.end) === 0 ? "24:00" : hm(minutesOf(preset.end)));
      var allDay = el("input"); allDay.type = "checkbox"; allDay.checked = !!preset.allDay;
      var reason = el("input"); reason.type = "text"; reason.maxLength = 200;
      reason.placeholder = "e.g. On leave, conference, lunch break";

      var row1 = el("div", "cal-form-row");
      row1.appendChild(field("From", startDate));
      var st = field("Start time", startTime); row1.appendChild(st);
      var row2 = el("div", "cal-form-row");
      row2.appendChild(field("To", endDate));
      var et = field("End time", endTime); row2.appendChild(et);
      var allDayLabel = el("label", "cal-check");
      allDayLabel.appendChild(allDay);
      allDayLabel.appendChild(el("span", null, "All day (e.g. leave)"));

      function syncAllDay() { st.hidden = et.hidden = allDay.checked; }
      allDay.addEventListener("change", syncAllDay);
      syncAllDay();

      form.appendChild(allDayLabel);
      form.appendChild(row1);
      form.appendChild(row2);
      form.appendChild(field("Reason (optional)", reason));
      var err = el("p", "cal-error"); err.hidden = true; form.appendChild(err);
      var conflictBox = el("div", "cal-conflicts"); conflictBox.hidden = true; form.appendChild(conflictBox);
      body.appendChild(form);

      function range() {
        var s, e;
        if (allDay.checked) {
          s = parseLocal(startDate.value);
          e = addDays(parseLocal(endDate.value), 1);
        } else {
          s = parseLocal(startDate.value + "T" + startTime.value);
          e = endTime.value === "24:00" ? addDays(parseLocal(endDate.value), 1) : parseLocal(endDate.value + "T" + endTime.value);
        }
        return [s, e];
      }

      var saveBtn;
      function submit(cancelConflicts) {
        err.hidden = true;
        if (!startDate.value || !endDate.value) { err.textContent = "Choose the dates."; err.hidden = false; return; }
        var r = range();
        if (r[1] <= r[0]) { err.textContent = "The end must be after the start."; err.hidden = false; return; }
        saveBtn.disabled = true;
        api("POST", URLS.absences, {
          start: isoLocal(r[0]), end: isoLocal(r[1]), reason: reason.value, cancel_conflicts: !!cancelConflicts,
        }).then(function (res) {
          saveBtn.disabled = false;
          if (res.status === 409) {
            conflictBox.innerHTML = "";
            conflictBox.appendChild(el("p", "cal-conflicts-title", res.data.error + " Patients will see these as cancelled:"));
            var ul = el("ul");
            (res.data.conflicts || []).forEach(function (c) { ul.appendChild(el("li", null, c.patient_name + " — " + c.when)); });
            conflictBox.appendChild(ul);
            conflictBox.appendChild(button("Block and cancel " + res.data.conflicts.length + " appointment" + (res.data.conflicts.length === 1 ? "" : "s"), "cal-btn cal-btn-danger", function () { submit(true); }));
            conflictBox.hidden = false;
            return;
          }
          if (!res.ok) { err.textContent = res.data.error || "Couldn't block that time."; err.hidden = false; return; }
          closeDialog();
          var n = (res.data.cancelled || []).length;
          toast(n ? "Time blocked and " + n + " appointment" + (n === 1 ? "" : "s") + " cancelled." : "Time blocked. Patients can't book it now.");
          state.weekStart = mondayOf(r[0]);
          load();
        });
      }
      form.addEventListener("submit", function (ev) { ev.preventDefault(); submit(false); });

      actions.appendChild(button("Cancel", "cal-btn", closeDialog));
      saveBtn = button("Block time", "cal-btn cal-btn-primary", function () { submit(false); });
      actions.appendChild(saveBtn);
      setTimeout(function () { reason.focus(); }, 30);
    });
  }

  // ------------------------------------------------------------------ toolbar
  root.querySelector("[data-cal-prev]").addEventListener("click", function () { state.weekStart = addDays(state.weekStart, -7); load(); });
  root.querySelector("[data-cal-next]").addEventListener("click", function () { state.weekStart = addDays(state.weekStart, 7); load(); });
  root.querySelector("[data-cal-today]").addEventListener("click", function () { state.weekStart = mondayOf(state.now); load(); });
  root.querySelector("[data-cal-block]").addEventListener("click", function () {
    var today = startOfDay(state.now);
    openBlockForm({ start: today, end: addDays(today, 1), allDay: true });
  });
  els.dialog.addEventListener("click", function (ev) { if (ev.target === els.dialog) closeDialog(); });
  els.dialog.querySelector("[data-dlg-close]").addEventListener("click", closeDialog);

  window.SvasthaDoctorCalendar = { reload: load };
  state.weekStart = mondayOf(new Date());
  load();
})();
