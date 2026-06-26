from __future__ import annotations

import re


SENSITIVE_RE = re.compile(
    r"(?i)(password|passwd|pwd|token|secret|api[_-]?key|bearer|authorization|otp|2fa|mfa)"
)
CHALLENGE_RE = re.compile(
    r"(?i)(cloudflare|just a moment|verify you are human|checking your browser|security challenge|"
    r"turnstile|captcha|cf-challenge|cf_clearance|challenge-platform|РїРѕРґС‚РІРµСЂРґРёС‚Рµ|РїСЂРѕРІРµСЂРєР°|РєР°РїС‡Р°)"
)
MANUAL_REQUIRED_RE = re.compile(
    r"(?i)(sign in|log in|login|password|one-time code|two-factor|2fa|otp|"
    r"РІРѕР№С‚Рё|Р»РѕРіРёРЅ|РїР°СЂРѕР»СЊ|Р°РІС‚РѕСЂРёР·Р°С†|РѕРґРЅРѕСЂР°Р·РѕРІ|РєРѕРґ РїРѕРґС‚РІРµСЂР¶РґРµРЅРёСЏ|sso\.saby\.ru|/auth|/login)"
)
CHROME_RECOVERY_RE = re.compile(
    r"(?i)(chrome exited early|devtoolsactiveport|error while loading shared libraries|daemon already running|profile appears to be in use)"
)
RESOURCE_EXHAUSTED_RE = re.compile(
    r"(?i)(resource temporarily unavailable|pthread_create|fork:|failed to start browserthread|pids\.max)"
)
APT_LOCK_RE = re.compile(r"(?i)(could not get lock|unable to acquire|unable to lock directory)")
