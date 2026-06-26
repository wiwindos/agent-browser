(async () => {
  "use strict";

  const options = window.__SABY_TENDERS_OPTIONS__ || {};
  const SCRIPT_VERSION = "0.3.61-fast-target";
  const STARTED_AT = Date.now();
  const MAX_RUNTIME_MS = Math.max(0, Number(options.maxRuntimeMs || 0));
  const SELECTORS = options.selectors || {};

  // Логи по умолчанию выключены, чтобы не тормозить слабый ПК.
  const DEBUG = Boolean(options.debug);
  const dlog = (...args) => {
    if (DEBUG) console.log(...args);
  };
  const dwarn = (...args) => {
    if (DEBUG) console.warn(...args);
  };

  // Быстрый сбор включен по умолчанию.
  // Чтобы вернуть старое поведение: { fullScan: true } или { fastTargetScan: false }
  const USE_FAST_TARGET_SCAN =
    !options.fullScan && options.fastTargetScan !== false;

  const TEMPLATE =
    options.template ||
    window.ClipboardSpy?.template ||
    "https://trade.saby.ru/page/tender-card/{id}";

  const ROW_SEL =
    options.rowSelector ||
    SELECTORS.row ||
    '[class*="controls-ListView__itemContent"]';

  const NEXT_SEL =
    options.nextSelector ||
    SELECTORS.next ||
    '[data-qa="Paging__Next"], .controls-Paging__btn-Next, [title*="Р’РїРµСЂ"], [aria-label*="Р’РїРµСЂ"], button, [role="button"]';

  const DATE_SEL =
    options.dateSelector ||
    SELECTORS.date ||
    ".tender-ItemTemplate__publishdate";

  const RU_DATE_RE = /\b\d{1,2}\.\d{1,2}\.(?:\d{2}|\d{4})\b/;
  const RU_DATE_PARSE_RE = /\b(\d{1,2})\.(\d{1,2})\.(\d{2}|\d{4})\b/;
  const INTERNAL_ID_RE = /\b\d{7,}\b/g;

  const norm = (s) => String(s ?? "").replace(/\s+/g, " ").trim();
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  function remainingRuntimeMs() {
    if (!MAX_RUNTIME_MS) return Infinity;
    return Math.max(0, MAX_RUNTIME_MS - (Date.now() - STARTED_AT));
  }

  function runtimeExpired() {
    return MAX_RUNTIME_MS > 0 && remainingRuntimeMs() <= 0;
  }

  function collectionCompleteForStopReason(reason) {
    const s = norm(reason).toLowerCase();
    if (!s) return false;
    if (s.includes("time budget")) return false;
    if (s.includes("max clicks")) return false;
    if (s.includes("rows did not change")) return false;
    if (s.includes("older than target but not confirmed")) return false;
    return true;
  }

  function pad2(n) {
    return String(n).padStart(2, "0");
  }

  function dateToKey(d) {
    return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
  }

  function dateToRuShort(d) {
    return `${pad2(d.getDate())}.${pad2(d.getMonth() + 1)}.${String(
      d.getFullYear()
    ).slice(-2)}`;
  }

  function getYesterdayDate() {
    const now = new Date();
    return new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1);
  }

  function parseTargetDate() {
    if (!options.targetDate) return getYesterdayDate();

    const m = String(options.targetDate).match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (!m) return getYesterdayDate();

    return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  }

  const TARGET_DATE = parseTargetDate();
  const TARGET_KEY = dateToKey(TARGET_DATE);
  const TARGET_TEXT = dateToRuShort(TARGET_DATE);

  const RUN_KEY = [
    TARGET_KEY,
    options.mode || "yesterday",
    options.filterText || "",
    TEMPLATE,
  ].join(" | ");

  function getRunState() {
    const existing = window.__SABY_TENDERS_STATE__;
    const canResume = options.resumeState !== false && !options.resetState;

    if (canResume && existing && existing.runKey === RUN_KEY) {
      existing.resumed = true;
      return existing;
    }

    const fresh = {
      runKey: RUN_KEY,
      foundEntries: [],
      seenKeys: [],
      steps: [],
      foundTarget: false,
      complete: false,
      resumed: false,
    };

    window.__SABY_TENDERS_STATE__ = fresh;
    return fresh;
  }

  function parseRuDateToKey(text) {
    const m = norm(text).match(RU_DATE_PARSE_RE);
    if (!m) return "";

    const day = Number(m[1]);
    const month = Number(m[2]);
    let year = Number(m[3]);

    if (year < 100) year = 2000 + year;

    return `${year}-${pad2(month)}-${pad2(day)}`;
  }

  function getPublishDateText(row, rawText = "") {
    const dateEl = row.querySelector(DATE_SEL);

    const direct = norm(dateEl?.innerText || dateEl?.textContent || "");
    if (direct) return direct;

    const raw = rawText
      ? norm(rawText)
      : norm(row.innerText || row.textContent || "");

    const m = raw.match(RU_DATE_RE);
    return m ? m[0] : "";
  }

  function findInternalId(rowEl, maxUp = 8) {
    const scoreLen = (n) => {
      const L = String(n).length;
      if (L === 9) return 100;
      if (L === 8 || L === 10) return 80;
      if (L >= 7 && L <= 12) return 50;
      return 0;
    };

    let bestId = "";
    let bestScore = -Infinity;
    let el = rowEl;

    for (let up = 0; up <= maxUp && el; up++, el = el.parentElement) {
      if (!el.attributes) continue;

      for (let i = 0; i < el.attributes.length; i++) {
        const attr = el.attributes[i];
        const val = norm(attr.value);
        if (!val) continue;

        const matches = val.match(INTERNAL_ID_RE);
        if (!matches) continue;

        const attrBonus = /(data-|id|key|uid|guid)/i.test(attr.name) ? 10 : 0;

        for (const id of matches) {
          const score = scoreLen(id) + attrBonus - up;

          if (score > bestScore) {
            bestScore = score;
            bestId = id;
          }
        }
      }
    }

    return bestId;
  }

  // Полный сбор строк. Используется для mode="visible" и как fallback.
  function collectAllRows({ silent = false } = {}) {
    const rows = Array.from(document.querySelectorAll(ROW_SEL));

    const items = rows.map((row, i) => {
      const raw = (row.innerText || row.textContent || "").trim();
      const publishDate = getPublishDateText(row, raw);
      const publishDateKey = parseRuDateToKey(publishDate);
      const internalId = findInternalId(row);
      const link = internalId ? TEMPLATE.replace("{id}", internalId) : "";

      return {
        i,
        publishDate,
        publishDateKey,
        internalId,
        link,
        raw,
      };
    });

    if (!silent) {
      dlog(
        "rows in DOM:",
        rows.length,
        "with id:",
        items.filter((x) => x.internalId).length,
        "target date:",
        TARGET_TEXT
      );
    }

    return items;
  }

  // Быстрый универсальный сбор под целевую дату.
  // TARGET_KEY может быть вчерашней датой или options.targetDate.
  // id/link считаются только для строк целевой даты.
  function collectRowsForTargetDateScan({ silent = false } = {}) {
    const rows = Array.from(document.querySelectorAll(ROW_SEL));

    const items = rows.map((row, i) => {
      const raw = (row.innerText || row.textContent || "").trim();
      const publishDate = getPublishDateText(row, raw);
      const publishDateKey = parseRuDateToKey(publishDate);

      let internalId = "";
      let link = "";

      if (publishDateKey === TARGET_KEY) {
        internalId = findInternalId(row);
        link = internalId ? TEMPLATE.replace("{id}", internalId) : "";
      }

      return {
        i,
        publishDate,
        publishDateKey,
        internalId,
        link,
        raw,
      };
    });

    if (!silent) {
      dlog(
        "rows in DOM:",
        rows.length,
        "with id:",
        items.filter((x) => x.internalId).length,
        "target date:",
        TARGET_TEXT,
        "fastTargetScan:",
        USE_FAST_TARGET_SCAN
      );
    }

    return items;
  }

  function makeStrongKey(item) {
    return [
      item.publishDateKey || "",
      item.publishDate || "",
      norm(item.raw).slice(0, 1800),
    ].join(" | ");
  }

  function analyzeBatch(items) {
    const uniqueDatesSet = new Set();

    let hasTarget = false;
    let hasOlder = false;
    let hasNewer = false;
    let keyCount = 0;
    let olderCount = 0;

    for (const item of items) {
      if (item.publishDate) {
        uniqueDatesSet.add(item.publishDate);
      }

      const key = item.publishDateKey;
      if (!key) continue;

      keyCount++;

      if (key === TARGET_KEY) hasTarget = true;

      if (key < TARGET_KEY) {
        hasOlder = true;
        olderCount++;
      }

      if (key > TARGET_KEY) {
        hasNewer = true;
      }
    }

    return {
      uniqueDates: Array.from(uniqueDatesSet),
      hasTarget,
      hasOlder,
      hasNewer,
      allOlder: keyCount > 0 && olderCount === keyCount,
    };
  }

  function findNextButton() {
    const buttons = Array.from(document.querySelectorAll(NEXT_SEL));

    return buttons.find((btn) => {
      const text = norm(btn.innerText || btn.textContent || "");
      const title = norm(btn.getAttribute("title"));
      const aria = norm(btn.getAttribute("aria-label"));
      const qa = norm(btn.getAttribute("data-qa"));
      const cls = String(btn.className || "");
      const label = norm([text, title, aria, qa, cls].join(" "));

      const looksLikeNext =
        qa === "Paging__Next" ||
        title === "Р’РїРµСЂС‘Рґ" ||
        title === "Р’РїРµСЂРµРґ" ||
        aria === "Р’РїРµСЂС‘Рґ" ||
        aria === "Р’РїРµСЂРµРґ" ||
        /Paging__btn-Next/.test(cls) ||
        /Р’РїРµСЂ[РµС‘]Рґ/i.test(label) ||
        /\b(next|forward)\b/i.test(label);

      if (!looksLikeNext) return false;

      const disabled =
        btn.disabled ||
        btn.getAttribute("aria-disabled") === "true" ||
        /disabled|readonly|state-disabled|_disabled|controls-disabled/i.test(cls);

      return !disabled;
    });
  }

  function findScrollContainer() {
    const rows = Array.from(document.querySelectorAll(ROW_SEL));
    let el = rows[0]?.parentElement;

    while (el && el !== document.body) {
      if (el.scrollHeight > el.clientHeight + 80) return el;
      el = el.parentElement;
    }

    return document.scrollingElement || document.documentElement;
  }

  function strongClick(el) {
    if (!el) return;

    el.scrollIntoView({ block: "center", inline: "center" });

    const opts = {
      bubbles: true,
      cancelable: true,
      view: window,
    };

    el.dispatchEvent(new MouseEvent("mouseover", opts));
    el.dispatchEvent(new MouseEvent("mousemove", opts));
    el.dispatchEvent(new MouseEvent("mousedown", opts));
    el.dispatchEvent(new MouseEvent("mouseup", opts));
    el.click();
  }

  function scrollForMoreRows() {
    const scroller = findScrollContainer();
    if (!scroller) return false;

    const before = scroller.scrollTop;

    scroller.scrollTop = Math.min(
      scroller.scrollHeight,
      scroller.scrollTop + Math.max(1400, scroller.clientHeight * 1.8)
    );

    scroller.dispatchEvent(new Event("scroll", { bubbles: true }));
    window.dispatchEvent(new Event("scroll"));

    return scroller.scrollTop !== before;
  }

  function visibleRowsSignature(items = collectAllRows({ silent: true })) {
    return items
      .map((item) =>
        [
          item.publishDateKey || "",
          item.publishDate || "",
          norm(item.raw).slice(0, 900),
        ].join(" | ")
      )
      .join("\n");
  }

  async function waitForRowsChanged(
    previousSignature,
    previousCount,
    timeout = 5000,
    collector = collectAllRows
  ) {
    const started = Date.now();

    while (Date.now() - started < timeout && !runtimeExpired()) {
      await sleep(250);

      const items = collector({ silent: true });
      const count = items.length;
      const signature = visibleRowsSignature(items);

      if (count > previousCount || signature !== previousSignature) {
        return true;
      }
    }

    return false;
  }

  async function waitForInitialRows(
    timeout = Number(options.initialRowsTimeoutMs || 12000)
  ) {
    const started = Date.now();

    while (Date.now() - started < timeout && !runtimeExpired()) {
      if (document.querySelectorAll(ROW_SEL).length > 0) return true;
      await sleep(250);
    }

    return document.querySelectorAll(ROW_SEL).length > 0;
  }

  function downloadCSV(
    items,
    filename = `tenders_${TARGET_TEXT}_${Date.now()}.csv`
  ) {
    if (!items?.length) {
      dwarn("No data to export");
      return;
    }

    const headers = Array.from(new Set(items.flatMap((o) => Object.keys(o))));
    const esc = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;

    const csv = [
      headers.join(","),
      ...items.map((o) => headers.map((h) => esc(o[h])).join(",")),
    ].join("\n");

    const blob = new Blob(["\uFEFF" + csv], {
      type: "text/csv;charset=utf-8",
    });

    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = filename;

    document.body.appendChild(a);
    a.click();
    a.remove();

    setTimeout(() => URL.revokeObjectURL(a.href), 5000);
  }

  async function collectTargetDate({
    delayAfterClick = Number(options.delayAfterClick || 600),
    maxClicks = Number(options.maxClicks || 300),
    stopAfterNoGrowth = Number(options.stopAfterNoGrowth || 4),
    olderBatchConfirmations = Number(options.olderBatchConfirmations || 3),
  } = {}) {
    const runState = getRunState();

    const found = new Map(
      Array.isArray(runState.foundEntries) ? runState.foundEntries : []
    );

    const seenRows = new Set(
      Array.isArray(runState.seenKeys) ? runState.seenKeys : []
    );

    const steps = Array.isArray(runState.steps) ? runState.steps.slice() : [];
    const stepOffset = steps.length;

    const rowCollector = USE_FAST_TARGET_SCAN
      ? collectRowsForTargetDateScan
      : collectAllRows;

    let foundTarget = Boolean(runState.foundTarget) || found.size > 0;
    let noGrowthCount = 0;
    let olderNoTargetStreak = Number(runState.olderNoTargetStreak || 0);
    let stopReason = "";
    let lastAllInfo = analyzeBatch([]);

    dlog("Target publish date:", TARGET_TEXT, TARGET_KEY);
    dlog("fastTargetScan:", USE_FAST_TARGET_SCAN);

    await waitForInitialRows();

    for (let localStep = 0; localStep <= maxClicks; localStep++) {
      const step = stepOffset + localStep;

      if (runtimeExpired()) {
        stopReason = "time budget reached before next collection step";
        dlog("Stopped:", stopReason);
        break;
      }

      const all = rowCollector();
      const batch = [];
      const keyByItem = new Map();

      for (const item of all) {
        const key = makeStrongKey(item);
        keyByItem.set(item, key);

        if (!seenRows.has(key)) {
          seenRows.add(key);
          batch.push(item);
        }
      }

      const targetItems = batch.filter((x) => x.publishDateKey === TARGET_KEY);
      let added = 0;

      for (const item of targetItems) {
        const key = keyByItem.get(item) || makeStrongKey(item);

        if (!found.has(key)) {
          found.set(key, {
            ...item,
            collectedStep: step,
          });
          added++;
        }
      }

      if (targetItems.length > 0) foundTarget = true;

      const batchInfo = analyzeBatch(batch);
      const allInfo = analyzeBatch(all);
      lastAllInfo = allInfo;

      dlog(
        `step ${step}: totalRows=${all.length}, newBatch=${batch.length}, targetInBatch=${targetItems.length}, added=${added}, total=${found.size}`
      );
      dlog("new batch dates:", batchInfo.uniqueDates.join(", "));
      dlog("all DOM dates:", allInfo.uniqueDates.join(", "));

      steps.push({
        step,
        totalRows: all.length,
        newBatch: batch.length,
        targetInBatch: targetItems.length,
        added,
        total: found.size,
        batchDates: batchInfo.uniqueDates,
        allDates: allInfo.uniqueDates,
        olderNoTargetStreak,
      });

      if (
        foundTarget &&
        batch.length > 0 &&
        !batchInfo.hasTarget &&
        batchInfo.hasOlder
      ) {
        olderNoTargetStreak++;

        if (olderNoTargetStreak >= olderBatchConfirmations) {
          stopReason = `confirmed older than target date after ${olderNoTargetStreak} batches`;
          dlog("Stopped:", stopReason);
          break;
        }
      } else if (batchInfo.hasTarget || batchInfo.hasNewer) {
        olderNoTargetStreak = 0;
      }

      if (!foundTarget && batch.length > 0 && batchInfo.allOlder) {
        stopReason = "reached dates older than target without matches";
        dlog("Stopped:", stopReason);
        break;
      }

      const next = findNextButton();

      const beforeCount = all.length;
      const beforeSignature = visibleRowsSignature(all);
      let action = "next-click";

      if (next) {
        dlog("Clicking next page...");
        strongClick(next);
      } else {
        action = "scroll";
        dlog("Next button not found; scrolling list...");

        if (!scrollForMoreRows()) {
          stopReason =
            "next button not found and scroll container is already at the end";
          dlog("Stopped:", stopReason);
          break;
        }
      }

      const sleepMs = Math.min(
        delayAfterClick,
        Math.max(0, remainingRuntimeMs())
      );

      if (sleepMs > 0) {
        await sleep(sleepMs);
      }

      if (runtimeExpired()) {
        stopReason = `time budget reached after ${action}`;
        dlog("Stopped:", stopReason);
        break;
      }

      const changeTimeout = Math.min(
        5000,
        Math.max(250, remainingRuntimeMs())
      );

      let changed = await waitForRowsChanged(
        beforeSignature,
        beforeCount,
        changeTimeout,
        rowCollector
      );

      if (!changed && action === "next-click" && !runtimeExpired()) {
        dwarn("Next click did not change rows; trying scroll fallback...");

        action = "next-click+scroll";

        if (scrollForMoreRows()) {
          const afterClickItems = rowCollector({ silent: true });
          const afterClickSignature = visibleRowsSignature(afterClickItems);
          const fallbackTimeout = Math.min(
            5000,
            Math.max(250, remainingRuntimeMs())
          );

          changed = await waitForRowsChanged(
            afterClickSignature,
            afterClickItems.length,
            fallbackTimeout,
            rowCollector
          );
        }
      }

      if (!changed) {
        noGrowthCount++;

        dwarn(
          `Rows did not change after ${action}: ${noGrowthCount}/${stopAfterNoGrowth}`
        );

        if (noGrowthCount >= stopAfterNoGrowth) {
          if (foundTarget && !lastAllInfo.hasTarget && lastAllInfo.hasOlder) {
            stopReason = `confirmed stable end after older than target rows and repeated ${action}`;
          } else {
            stopReason = `rows did not change after repeated ${action}`;
          }

          dlog("Stopped:", stopReason);
          break;
        }
      } else {
        noGrowthCount = 0;
      }
    }

    if (!stopReason) {
      stopReason = "max clicks reached";
      dlog("Stopped:", stopReason);
    }

    const result = Array.from(found.values());
    const complete = collectionCompleteForStopReason(stopReason);

    runState.foundEntries = Array.from(found.entries());
    runState.seenKeys = Array.from(seenRows);
    runState.steps = steps;
    runState.foundTarget = foundTarget;
    runState.olderNoTargetStreak = olderNoTargetStreak;
    runState.stopReason = stopReason;
    runState.complete = complete;
    runState.total = result.length;
    runState.runtimeMs = Date.now() - STARTED_AT;
    runState.maxRuntimeMs = MAX_RUNTIME_MS;
    runState.fastTargetScan = USE_FAST_TARGET_SCAN;

    window.SabyTenderLinks.lastRun = {
      targetText: TARGET_TEXT,
      targetKey: TARGET_KEY,
      stopReason,
      complete,
      resumed: Boolean(runState.resumed),
      steps,
      total: result.length,
      runtimeMs: Date.now() - STARTED_AT,
      maxRuntimeMs: MAX_RUNTIME_MS,
      fastTargetScan: USE_FAST_TARGET_SCAN,
    };

    console.log(
      "Collected target-date tenders:",
      result.length,
      "| complete:",
      complete,
      "| stopReason:",
      stopReason,
      "| target:",
      TARGET_TEXT,
      "| fastTargetScan:",
      USE_FAST_TARGET_SCAN
    );

    if (DEBUG) {
      console.log("First items:", result.slice(0, 10));
    }

    return result;
  }

  // Алиас оставлен, чтобы старые вызовы не сломались.
  async function collectYesterday(args = {}) {
    return collectTargetDate(args);
  }

  window.SabyTenderLinks = {
    TARGET_TEXT,
    TARGET_KEY,
    ROW_SEL,
    NEXT_SEL,
    DATE_SEL,
    collectAllRows,
    collectRowsForTargetDateScan,
    collectTargetDate,
    collectYesterday,
    downloadCSV,
    findNextButton,
    visibleRowsSignature,
  };

  let items;

  if (options.mode === "visible") {
    items = collectAllRows();
  } else {
    items = await collectTargetDate();
  }

  if (options.filterText) {
    const needle = String(options.filterText).toLowerCase();

    items = items.filter((item) =>
      norm(item.raw).toLowerCase().includes(needle)
    );
  }

  if (Number(options.limit || 0) > 0) {
    items = items.slice(0, Number(options.limit));
  }

  if (options.downloadInBrowser) {
    downloadCSV(items);
  }

  const complete =
    options.mode === "visible"
      ? true
      : Boolean(window.SabyTenderLinks.lastRun?.complete);

  const nextAction = complete
    ? "none"
    : "send the partial CSV, stop this agent run, and ask the user whether to continue with one more action=saby_tenders_csv profile=saby mode=yesterday resume_state=true pass";

  return {
    url: location.href,
    title: document.title,
    targetText: TARGET_TEXT,
    targetKey: TARGET_KEY,
    scriptVersion: SCRIPT_VERSION,
    rowSelector: ROW_SEL,
    rows: document.querySelectorAll(ROW_SEL).length,
    withId: items.filter((item) => item.internalId).length,
    mode: options.mode || "yesterday",
    filterText: options.filterText || "",
    stopReason: window.SabyTenderLinks.lastRun?.stopReason || "",
    complete,
    resumed: Boolean(window.SabyTenderLinks.lastRun?.resumed),
    nextAction,
    steps: window.SabyTenderLinks.lastRun?.steps || [],
    runtimeMs: Date.now() - STARTED_AT,
    maxRuntimeMs: MAX_RUNTIME_MS,
    fastTargetScan: USE_FAST_TARGET_SCAN,
    items,
  };
})();