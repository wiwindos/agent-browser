"use strict";

const fs = require("fs");
const path = require("path");
const vm = require("vm");

function logToStderr(method, args) {
  const line = args.map((value) => {
    if (typeof value === "string") return value;
    try {
      return JSON.stringify(value);
    } catch {
      return String(value);
    }
  }).join(" ");
  process.stderr.write(`[collector:${method}] ${line}\n`);
}

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

function stripTags(html) {
  return String(html || "")
    .replace(/<[^>]+>/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function parseAttrs(source) {
  const attrs = {};
  const pattern = /([a-zA-Z0-9:_-]+)="([^"]*)"/g;
  let match;
  while ((match = pattern.exec(source)) !== null) {
    attrs[match[1]] = match[2];
  }
  return attrs;
}

class FakeElement {
  constructor(attrs = {}, text = "", html = "") {
    this._attrs = attrs;
    this._text = text;
    this._html = html;
    this.attributes = Object.entries(attrs).map(([name, value]) => ({ name, value }));
    this.parentElement = null;
    this.className = attrs.class || "";
    this.disabled = false;
  }

  get innerText() {
    return this._text;
  }

  get textContent() {
    return this._text;
  }

  getAttribute(name) {
    return this._attrs[name] || "";
  }

  querySelector(selector) {
    if (selector.includes("tender-ItemTemplate__publishdate")) {
      const match = this._html.match(
        /<div class="tender-ItemTemplate__publishdate">([\s\S]*?)<\/div>/i
      );
      if (!match) return null;
      return new FakeElement({ class: "tender-ItemTemplate__publishdate" }, stripTags(match[1]), match[0]);
    }
    return null;
  }

  scrollIntoView() {}
  dispatchEvent() { return true; }
  click() {}
  appendChild() {}
  remove() {}
}

function parseRows(html) {
  const rows = [];
  const pattern =
    /<div class="controls-ListView__itemContent"([^>]*)>([\s\S]*?)<\/div>\s*(?=<div class="controls-ListView__itemContent"|<button|<\/body>)/gi;
  let match;
  while ((match = pattern.exec(html)) !== null) {
    const attrs = parseAttrs(match[1]);
    const rowHtml = `<div class="controls-ListView__itemContent"${match[1]}>${match[2]}</div>`;
    const row = new FakeElement(
      { class: "controls-ListView__itemContent", ...attrs },
      stripTags(match[2]),
      rowHtml
    );
    rows.push(row);
  }
  return rows;
}

function parseButton(html) {
  const match = html.match(/<button([^>]*)>([\s\S]*?)<\/button>/i);
  if (!match) return null;
  const attrs = parseAttrs(match[1]);
  const button = new FakeElement(attrs, stripTags(match[2]), match[0]);
  button.className = attrs.class || "";
  return button;
}

async function main() {
  const fixturePath = process.argv[2];
  const collectorPath = process.argv[3];
  const selectorsPath = process.argv[4];
  const optionsJson = process.argv[5] || "{}";
  if (!fixturePath || !collectorPath || !selectorsPath) {
    throw new Error("usage: node fixture_runner.js <fixture> <collector> <selectors> [optionsJson]");
  }

  const html = fs.readFileSync(fixturePath, "utf8");
  const collectorSource = fs.readFileSync(collectorPath, "utf8");
  const selectors = readJson(selectorsPath);
  const titleMatch = html.match(/<title>([\s\S]*?)<\/title>/i);
  const title = titleMatch ? stripTags(titleMatch[1]) : path.basename(fixturePath);
  const rows = parseRows(html);
  const button = parseButton(html);
  const scrollingElement = { scrollTop: 0, scrollHeight: 1000, clientHeight: 600, dispatchEvent() { return true; } };
  const documentElement = { scrollTop: 0, scrollHeight: 1000, clientHeight: 600, dispatchEvent() { return true; } };
  const document = {
    title,
    body: { appendChild() {}, removeChild() {} },
    scrollingElement,
    documentElement,
    querySelectorAll(selector) {
      if (selector.includes("controls-ListView__itemContent")) return rows;
      if (selector.includes("Paging__Next") || selector.includes("button")) return button ? [button] : [];
      return [];
    },
    createElement() {
      return new FakeElement();
    },
  };
  const window = {
    __SABY_TENDERS_OPTIONS__: {
      mode: "visible",
      targetDate: "2026-06-04",
      ...JSON.parse(optionsJson),
      selectors,
      rowSelector: selectors.row,
      nextSelector: selectors.next,
      dateSelector: selectors.date,
    },
    ClipboardSpy: null,
  };
  window.window = window;

  const context = {
    window,
    document,
    location: { href: `file://${fixturePath}` },
    console: {
      log: (...args) => logToStderr("log", args),
      warn: (...args) => logToStderr("warn", args),
      error: (...args) => logToStderr("error", args),
      table: (...args) => logToStderr("table", args),
    },
    Blob: class Blob {
      constructor(parts) { this.parts = parts; }
    },
    URL: {
      createObjectURL() { return "blob:test"; },
      revokeObjectURL() {},
    },
    MouseEvent: class MouseEvent {},
    Event: class Event {},
    setTimeout,
    clearTimeout,
    Promise,
  };
  context.globalThis = context;

  const result = await vm.runInNewContext(collectorSource, context, { filename: collectorPath });
  process.stdout.write(JSON.stringify(result));
}

main().catch((error) => {
  process.stderr.write(String(error && error.stack ? error.stack : error));
  process.exit(1);
});
