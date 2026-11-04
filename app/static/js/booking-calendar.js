document.addEventListener("alpine:init", () => {
  Alpine.data("bookingCalendar", (slotsByDate) => ({
    slotsByDate: slotsByDate || {},
    viewYear: null,
    viewMonth: null,
    selectedDate: null,
    selectedSlot: null,
    openPeriod: "morning",
    periods: ["morning", "afternoon", "evening"],
    periodLabels: { morning: "Morning", afternoon: "Afternoon", evening: "Evening" },
    weekdayLabels: ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],

    init() {
      const dates = Object.keys(this.slotsByDate).sort();
      const now = new Date();
      if (dates.length) {
        this.selectedDate = dates[0];
        const [y, m] = dates[0].split("-").map(Number);
        this.viewYear = y;
        this.viewMonth = m - 1;
        this.openPeriod = this.firstNonEmptyPeriod(dates[0]);
      } else {
        this.viewYear = now.getFullYear();
        this.viewMonth = now.getMonth();
      }
    },

    firstNonEmptyPeriod(dateStr) {
      const day = this.slotsByDate[dateStr];
      if (!day) return "morning";
      return this.periods.find((p) => day[p] && day[p].length) || "morning";
    },

    monthLabel() {
      const d = new Date(this.viewYear, this.viewMonth, 1);
      return d.toLocaleString("en-US", { month: "long", year: "numeric" });
    },

    prevMonth() {
      this.viewMonth -= 1;
      if (this.viewMonth < 0) {
        this.viewMonth = 11;
        this.viewYear -= 1;
      }
    },
    nextMonth() {
      this.viewMonth += 1;
      if (this.viewMonth > 11) {
        this.viewMonth = 0;
        this.viewYear += 1;
      }
    },

    calendarCells() {
      const first = new Date(this.viewYear, this.viewMonth, 1);
      let startOffset = first.getDay() - 1; // Monday-first week
      if (startOffset < 0) startOffset = 6;
      const daysInMonth = new Date(this.viewYear, this.viewMonth + 1, 0).getDate();
      const cells = [];
      for (let i = 0; i < startOffset; i++) cells.push(null);
      for (let d = 1; d <= daysInMonth; d++) {
        const mm = String(this.viewMonth + 1).padStart(2, "0");
        const dd = String(d).padStart(2, "0");
        cells.push(`${this.viewYear}-${mm}-${dd}`);
      }
      return cells;
    },

    totalForDate(dateStr) {
      const day = this.slotsByDate[dateStr];
      if (!day) return 0;
      return this.periods.reduce((sum, p) => sum + ((day[p] && day[p].length) || 0), 0);
    },
    hasSlots(dateStr) {
      return !!dateStr && this.totalForDate(dateStr) > 0;
    },
    dayNum(dateStr) {
      return dateStr ? parseInt(dateStr.split("-")[2], 10) : "";
    },
    selectDate(dateStr) {
      if (!this.hasSlots(dateStr)) return;
      this.selectedDate = dateStr;
      this.selectedSlot = null;
      this.openPeriod = this.firstNonEmptyPeriod(dateStr);
    },
    selectedDayPeriods() {
      return this.selectedDate ? this.slotsByDate[this.selectedDate] || {} : {};
    },
    togglePeriod(p) {
      this.openPeriod = this.openPeriod === p ? null : p;
    },
    selectSlot(iso) {
      this.selectedSlot = iso;
    },
    formattedSelectedDate() {
      if (!this.selectedDate) return "";
      const [y, m, d] = this.selectedDate.split("-").map(Number);
      const dt = new Date(y, m - 1, d);
      return dt.toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" });
    },
  }));
});
