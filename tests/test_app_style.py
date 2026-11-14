"""The app's look is one small set of tokens (app/css/app.css). These checks keep it that way.

- no color outside :root (every other rule uses a token), no gradient or shadow, one radius, tokenised font sizes
- both themes carry the agreed token values, and every text and background pair has contrast of at least 4.5:1
- no emoji or symbol characters anywhere in app/, and the old trust-pill labels are not shown as static text
Standard library only."""
import glob
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "app")
CSS_FILES = sorted(glob.glob(os.path.join(APP, "css", "*.css")))

LIGHT = {"bg": "#FFFFFF", "surface": "#F6F7F9", "border": "#D5DAE1", "text": "#1B2430", "muted": "#566274", "accent": "#1F4E79", "link": "#1F4E79",
         "supported": "#1E6B52", "contradicted": "#A12B2B", "insufficient": "#8A5A00", "stopped": "#4A4F5C"}
DARK = {"bg": "#11151B", "surface": "#181E26", "border": "#2B3441", "text": "#E6EAF0", "muted": "#9BA7B6", "accent": "#8DB8E8", "link": "#8DB8E8",
        "supported": "#6CC4A1", "contradicted": "#F19A9A", "insufficient": "#E5B85C", "stopped": "#B4BAC8"}
OLD_PILLS = ["Frozen data", "Numbers traced", "Limits shown", "Safety checks on", "A person decides"]


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def css_text():
    return "\n".join(re.sub(r"/\*.*?\*/", "", read(p), flags=re.S) for p in CSS_FILES)


def rules(css):
    """(selector, declarations) for every innermost block, including blocks inside @media."""
    stack, buf, out = [], "", []
    for ch in css:
        if ch == "{":
            stack.append(buf.strip()); buf = ""
        elif ch == "}":
            sel = stack.pop() if stack else ""
            if buf.strip():
                out.append((sel, buf))
            buf = ""
        else:
            buf += ch
    return out


def tokens(selector):
    css = css_text()
    for sel, decl in rules(css):
        if sel == selector:
            return {k: v.upper() for k, v in re.findall(r"--([\w-]+):\s*(#[0-9A-Fa-f]{6})", decl)}
    raise AssertionError("no rule for " + selector)


def luminance(h):
    r, g, b = [int(h.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def contrast(a, b):
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


class TestTokens(unittest.TestCase):
    def test_both_themes_carry_the_agreed_values(self):
        light = tokens(':root, :root[data-theme="light"]'); dark = tokens(':root[data-theme="dark"]')
        for k, v in LIGHT.items():
            self.assertEqual(light[k], v, "light --" + k)
        for k, v in DARK.items():
            self.assertEqual(dark[k], v, "dark --" + k)

    def test_text_and_background_pairs_have_enough_contrast(self):
        for name, t in (("light", tokens(':root, :root[data-theme="light"]')), ("dark", tokens(':root[data-theme="dark"]'))):
            for fg in ("text", "muted", "link", "accent", "supported", "contradicted", "insufficient", "stopped"):
                for bg in ("bg", "surface"):
                    self.assertGreaterEqual(contrast(t[fg], t[bg]), 4.5, f"{name}: --{fg} on --{bg}")
            self.assertGreaterEqual(contrast(t["on-accent"], t["accent"]), 4.5, f"{name}: primary button text")
            self.assertGreaterEqual(contrast(t["bg"], t["text"]), 4.5, f"{name}: toast text")
            self.assertGreaterEqual(contrast(t["bg"], t["insufficient"]), 4.5, f"{name}: banner text")


class TestStylesheet(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.css = css_text()
        cls.rules = rules(cls.css)

    def test_no_color_literal_outside_root(self):
        bad = [(s, m) for s, d in self.rules if not s.startswith(":root")
               for m in re.findall(r"#[0-9A-Fa-f]{3,8}\b|\brgba?\(|\bhsla?\(", d)]
        self.assertEqual(bad, [], "color literal outside :root: " + repr(bad[:5]))

    def test_no_gradients_or_shadows(self):
        self.assertNotIn("gradient(", self.css)
        shadows = [m for _, d in self.rules for m in re.findall(r"(?<![\w-])(?:box|text)-shadow:\s*([^;]+)", d) if m.strip() != "none"]
        self.assertEqual(shadows, [])

    def test_one_radius_and_no_pills(self):
        radii = {m.strip() for _, d in self.rules for m in re.findall(r"border-radius:\s*([^;]+)", d)}
        self.assertLessEqual(radii, {"var(--r)", "0"})

    def test_font_sizes_come_from_tokens(self):
        sizes = [m.strip() for _, d in self.rules for m in re.findall(r"(?<![\w-])font-size:\s*([^;]+)", d)]
        self.assertTrue(sizes)
        self.assertEqual([s for s in sizes if not re.fullmatch(r"var\(--fs-[a-z0-9-]+\)", s)], [])

    def test_content_width_and_control_height(self):
        self.assertIn("--w: 1040px", self.css)
        self.assertIn("--ctl: 36px", self.css)


class TestAppText(unittest.TestCase):
    FILES = [p for ext in ("js", "html", "css", "md") for p in glob.glob(os.path.join(APP, "**", "*." + ext), recursive=True)]
    SYMBOLS = re.compile("[\u2200-\u22ff\u2300-\u23ff\u2460-\u27bf\u2900-\u2bff\U0001F000-\U0001FFFF\ufe0f\u200d]")
    ESCAPED = re.compile(r"\\u\{1?[0-9a-fA-F]{4,5}\}|\\u(?:2[2-9a-bA-B][0-9a-fA-F]{2})|&#x1?[0-9a-fA-F]{4,5};")

    def test_there_are_files_to_check(self):
        self.assertGreater(len(self.FILES), 10)

    def test_no_emoji_or_symbol_characters(self):
        found = []
        for p in self.FILES:
            text = read(p)
            for m in list(self.SYMBOLS.finditer(text)) + list(self.ESCAPED.finditer(text)):
                found.append(f"{os.path.relpath(p, APP)}: {m.group(0)!r}")
        self.assertEqual(found, [])

    def test_old_pill_labels_are_gone(self):
        found = [f"{os.path.relpath(p, APP)}: {label}" for p in self.FILES if p.endswith(".js")
                 for label in OLD_PILLS if label in read(p)]
        self.assertEqual(found, [])


if __name__ == "__main__":
    unittest.main()
