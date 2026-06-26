from __future__ import annotations


CHROME_DEPS_BASE = [
    "ca-certificates",
    "fonts-liberation",
    "libglib2.0-0",
    "libnss3",
    "libnspr4",
    "libatk-bridge2.0-0",
    "libatk1.0-0",
    "libcups2",
    "libdrm2",
    "libdbus-1-3",
    "libxkbcommon0",
    "libxcomposite1",
    "libxdamage1",
    "libxfixes3",
    "libxrandr2",
    "libgbm1",
    "libasound2",
    "libpango-1.0-0",
    "libpangocairo-1.0-0",
    "libcairo2",
    "libx11-6",
    "libxcb1",
    "libxext6",
    "libxshmfence1",
    "libxrender1",
    "libgtk-3-0",
]
CHROME_DEPS_T64 = [
    dep + "t64" if dep in {"libatk-bridge2.0-0", "libatk1.0-0", "libcups2", "libasound2", "libgtk-3-0"} else dep
    for dep in CHROME_DEPS_BASE
]
DESKTOP_DEPS = [
    "xvfb",
    "x11vnc",
    "novnc",
    "websockify",
    "openbox",
    "dbus-x11",
    "xauth",
]
DESKTOP_RUNTIME_BINARIES = [
    ("Xvfb", "xvfb"),
    ("x11vnc", "x11vnc"),
    ("websockify", "websockify"),
    ("openbox", "openbox"),
]
