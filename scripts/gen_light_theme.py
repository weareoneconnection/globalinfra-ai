#!/usr/bin/env python3
"""Generate the light ("day") theme from the dark stylesheet.

``apps/web/app/globals.css`` is written for the dark theme and uses many
literal colours. Rather than maintaining a second hand-written stylesheet,
this script reads every rule that contains a colour and emits an override
scoped to ``:root[data-theme="light"]`` with each colour mapped to its light
counterpart: lightness is mirrored (dark panels become light, light text
becomes dark, bright accents become deeper accents) while hue and alpha are
kept; shadows stay dark but softer. The palette variables are then set by
hand in ``LIGHT_TOKENS`` for the final tuning.

Run after changing globals.css:

    python3 scripts/gen_light_theme.py

The output, ``apps/web/app/theme-light.css``, is committed and imported
after globals.css.
"""
from __future__ import annotations

import colorsys
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "apps" / "web" / "app" / "globals.css"
TARGET = ROOT / "apps" / "web" / "app" / "theme-light.css"
SCOPE = ':root[data-theme="light"]'

LIGHT_TOKENS = {
    "--bg": "#f3f7f9", "--bg2": "#eaf1f4", "--panel": "#ffffff", "--panel2": "#f6fafb",
    "--line": "rgba(32,72,92,.13)", "--line2": "rgba(32,72,92,.24)",
    "--text": "#0f2531", "--muted": "#587380",
    "--cyan": "#0b84a5", "--green": "#14865a", "--amber": "#b26a00", "--red": "#cf3c3c",
    "--blue": "#3b5bdb", "--orange": "#c4511a", "--violet": "#7a4bd8", "--teal": "#0d8478",
    "--shadow": "0 14px 40px rgba(20,50,70,.10)",
}

COLOR_RE = re.compile(
    r"#[0-9a-fA-F]{8}\b|#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3,4}\b|rgba?\([^()]*\)|\b(?:white|black)\b"
)
# The logo keeps its brand colours in both themes.
KEEP_SELECTORS = ("brand-mark",)
SHADOW_PROPS = {"box-shadow", "text-shadow", "filter", "-webkit-filter"}


def _parse(token: str) -> tuple[float, float, float, float | None]:
    if token == "white":
        return 1.0, 1.0, 1.0, None
    if token == "black":
        return 0.0, 0.0, 0.0, None
    if token.startswith("#"):
        h = token[1:]
        if len(h) in (3, 4):
            h = "".join(c * 2 for c in h)
        r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
        a = int(h[6:8], 16) / 255 if len(h) == 8 else None
        return r, g, b, a
    parts = [p.strip() for p in token[token.index("(") + 1:-1].replace("/", ",").split(",")]
    r, g, b = (float(p.rstrip("%")) * (2.55 if p.endswith("%") else 1) / 255 for p in parts[:3])
    a = None
    if len(parts) > 3:
        a = float(parts[3].rstrip("%")) / (100 if parts[3].endswith("%") else 1)
    return r, g, b, a


def _format(r: float, g: float, b: float, a: float | None) -> str:
    rgb = [max(0, min(255, round(c * 255))) for c in (r, g, b)]
    if a is None:
        return "#{:02x}{:02x}{:02x}".format(*rgb)
    alpha = f"{a:.3f}".rstrip("0").rstrip(".") or "0"
    if alpha.startswith("0."):
        alpha = alpha[1:]
    return f"rgba({rgb[0]},{rgb[1]},{rgb[2]},{alpha})"


def to_light(token: str, shadow: bool = False) -> str:
    r, g, b, a = _parse(token)
    h, lightness, s = colorsys.rgb_to_hls(r, g, b)
    if shadow and lightness < 0.2:
        # Shadows stay dark on a light page, only softer.
        return _format(0.08, 0.2, 0.27, (a if a is not None else 1) * 0.35)
    mirrored = 1 - lightness
    if lightness < 0.2:
        # Dark surfaces: in the dark theme raised panels are lighter than the
        # page; on a light page they should be whiter than it, so the order
        # is kept rather than mirrored (page ~95%, panels up to white).
        mirrored = min(1.0, 0.94 + lightness * 0.3)
        s *= 0.55
    elif 0.25 < lightness < 0.85 and s > 0.35:
        # Bright accents become deeper so they read on white.
        mirrored = min(mirrored, 0.42)
    nr, ng, nb = colorsys.hls_to_rgb(h, mirrored, s)
    return _format(nr, ng, nb, a)


def convert_value(prop: str, value: str) -> str:
    shadow = prop.strip().lower() in SHADOW_PROPS or "drop-shadow" in value
    return COLOR_RE.sub(lambda m: to_light(m.group(0), shadow), value)


def strip_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def blocks(css: str):
    """Yield (prelude, body) for each top-level block."""
    i, n = 0, len(css)
    while i < n:
        start = css.find("{", i)
        if start < 0:
            return
        depth, j = 1, start + 1
        while j < n and depth:
            depth += {"{": 1, "}": -1}.get(css[j], 0)
            j += 1
        yield css[i:start].strip(), css[start + 1:j - 1]
        i = j


def scope_selector(selector: str) -> str:
    out = []
    for part in selector.split(","):
        part = part.strip()
        if not part:
            continue
        if part.startswith(":root"):
            out.append(SCOPE + part[5:])
        elif re.match(r"html(?![\w-])", part):
            out.append(SCOPE + part[4:])
        else:
            out.append(f"{SCOPE} {part}")
    return ",".join(out)


def split_declarations(body: str) -> list[tuple[str, str]]:
    decls, depth, current = [], 0, ""
    for ch in body:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == ";" and depth == 0:
            decls.append(current)
            current = ""
        else:
            current += ch
    decls.append(current)
    pairs = []
    for decl in decls:
        if ":" in decl:
            prop, value = decl.split(":", 1)
            pairs.append((prop.strip(), value.strip()))
    return pairs


def convert(css: str) -> list[str]:
    rules = []
    for prelude, body in blocks(css):
        if prelude.startswith("@media") or prelude.startswith("@supports"):
            inner = convert(body)
            if inner:
                rules.append(prelude + "{" + "".join(inner) + "}")
            continue
        if prelude.startswith("@"):
            continue  # keyframes, font-face: left as in the dark theme
        if any(keep in prelude for keep in KEEP_SELECTORS):
            continue
        decls = [(p, convert_value(p, v)) for p, v in split_declarations(body)
                 if COLOR_RE.search(v) and not (p.startswith("--") and prelude == ":root")]
        if decls:
            rules.append(scope_selector(prelude) + "{" + ";".join(f"{p}:{v}" for p, v in decls) + "}")
    return rules


def main() -> None:
    rules = convert(strip_comments(SOURCE.read_text(encoding="utf-8")))
    tokens = ";".join(f"{k}:{v}" for k, v in LIGHT_TOKENS.items())
    header = ("/* Generated by scripts/gen_light_theme.py from globals.css -- do not edit by hand. */\n"
              f":root{{color-scheme:dark}}\n{SCOPE}{{color-scheme:light;{tokens}}}\n")
    TARGET.write_text(header + "\n".join(rules) + "\n", encoding="utf-8")
    print(f"wrote {TARGET.relative_to(ROOT)}: {len(rules)} rules")


if __name__ == "__main__":
    main()
