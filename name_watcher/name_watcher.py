"""
Teams caption name watcher.

Watches a screen region (e.g. Microsoft Teams live captions) with OCR and
alerts you when your name is spoken.

Usage:
    python name_watcher.py                 # uses saved region, or asks you to draw one
    python name_watcher.py --reselect      # draw a new region
    python name_watcher.py --name Keith --name "Keith Murphy" --speak
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageOps

CONFIG_FILE = Path.home() / ".name_watcher.json"
WORD_RE = re.compile(r"[A-Za-z0-9']+")


# --------------------------------------------------------------------------- #
# Matching (pure logic, no GUI / OCR dependencies -> easy to test)
# --------------------------------------------------------------------------- #
def _norm(word: str) -> str:
    w = word.lower().replace("'", "")
    # Common OCR confusions for letters in names
    return w.translate(str.maketrans({"1": "i", "l": "i", "|": "i", "0": "o", "5": "s"}))


def find_mentions(text: str, names: list[str], threshold: float = 0.8) -> list[str]:
    """Return the caption lines in `text` that contain a (fuzzy) match for any name."""
    targets = [[_norm(w) for w in WORD_RE.findall(n)] for n in names]
    hits = []
    for line in text.splitlines():
        words = [_norm(w) for w in WORD_RE.findall(line)]
        for target in targets:
            n = len(target)
            for i in range(len(words) - n + 1):
                cand = " ".join(words[i:i + n])
                tgt = " ".join(target)
                # Allow possessive / plural: "keiths"
                if cand.endswith("s") and not tgt.endswith("s"):
                    alt = cand[:-1]
                else:
                    alt = cand
                score = max(difflib.SequenceMatcher(None, cand, tgt).ratio(),
                            difflib.SequenceMatcher(None, alt, tgt).ratio())
                if score >= threshold:
                    hits.append(line.strip())
                    break
            else:
                continue
            break
    return hits


@dataclass
class Deduper:
    """Captions stay on screen for several seconds; alert once per caption line."""
    memory_s: float = 120.0
    similarity: float = 0.6
    seen: list[tuple[float, str]] = field(default_factory=list)

    def is_new(self, line: str, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        self.seen = [(t, s) for t, s in self.seen if now - t < self.memory_s]
        key = line.lower()
        for _, s in self.seen:
            if difflib.SequenceMatcher(None, key, s).ratio() >= self.similarity:
                return False
        self.seen.append((now, key))
        return True


# --------------------------------------------------------------------------- #
# OCR
# --------------------------------------------------------------------------- #
def preprocess(img: Image.Image) -> Image.Image:
    g = ImageOps.grayscale(img)
    # Teams captions are light text on a dark background; Tesseract prefers dark on light
    if sum(g.getdata()) / (g.width * g.height) < 128:
        g = ImageOps.invert(g)
    g = g.resize((g.width * 2, g.height * 2), Image.LANCZOS)
    return g.point(lambda p: 255 if p > 150 else 0)


def ocr(img: Image.Image) -> str:
    import pytesseract
    return pytesseract.image_to_string(preprocess(img), config="--psm 6")


def grab(sct, region: dict) -> Image.Image:
    shot = sct.grab(region)
    return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")


# --------------------------------------------------------------------------- #
# Region selection (drag a rectangle over a dimmed screenshot overlay)
# --------------------------------------------------------------------------- #
def select_region() -> dict | None:
    import tkinter as tk
    import mss

    with mss.mss() as sct:
        mon = sct.monitors[0]  # whole virtual desktop (all monitors)

    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.attributes("-alpha", 0.3)
    root.geometry(f"{mon['width']}x{mon['height']}+{mon['left']}+{mon['top']}")
    canvas = tk.Canvas(root, cursor="cross", bg="grey", highlightthickness=0)
    canvas.pack(fill="both", expand=True)
    canvas.create_text(mon["width"] // 2, 40, fill="white", font=("Segoe UI", 20, "bold"),
                       text="Drag over the Teams caption area  (Esc = cancel)")
    state: dict = {}

    def down(e):
        state["x0"], state["y0"] = e.x, e.y
        state["rect"] = canvas.create_rectangle(e.x, e.y, e.x, e.y, outline="red", width=3)

    def drag(e):
        canvas.coords(state["rect"], state["x0"], state["y0"], e.x, e.y)

    def up(e):
        x0, x1 = sorted((state["x0"], e.x))
        y0, y1 = sorted((state["y0"], e.y))
        if x1 - x0 > 10 and y1 - y0 > 10:
            state["region"] = {"left": x0 + mon["left"], "top": y0 + mon["top"],
                               "width": x1 - x0, "height": y1 - y0}
        root.destroy()

    canvas.bind("<ButtonPress-1>", down)
    canvas.bind("<B1-Motion>", drag)
    canvas.bind("<ButtonRelease-1>", up)
    root.bind("<Escape>", lambda e: root.destroy())
    root.focus_force()
    root.mainloop()
    return state.get("region")


# --------------------------------------------------------------------------- #
# Alerts
# --------------------------------------------------------------------------- #
def beep():
    try:
        if sys.platform == "win32":
            import winsound
            for _ in range(3):
                winsound.Beep(1200, 200)
        elif sys.platform == "darwin":
            import subprocess
            subprocess.Popen(["afplay", "/System/Library/Sounds/Glass.aiff"])
        else:
            print("\a", end="", flush=True)
    except Exception:
        print("\a", end="", flush=True)


def speak(text: str):
    try:
        import pyttsx3
        eng = pyttsx3.init()
        eng.say(text)
        eng.runAndWait()
    except Exception as exc:  # optional dependency
        print(f"(speech unavailable: {exc})")


# --------------------------------------------------------------------------- #
# App: small always-on-top status window that polls the region
# --------------------------------------------------------------------------- #
def run(args, region: dict):
    import tkinter as tk
    import mss

    sct = mss.mss()
    dedupe = Deduper()
    root = tk.Tk()
    root.title("Name watcher")
    root.attributes("-topmost", True)
    root.geometry("360x110")
    status = tk.StringVar(value=f"Watching for: {', '.join(args.name)}")
    last = tk.StringVar(value="")
    tk.Label(root, textvariable=status, font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=8, pady=(6, 0))
    tk.Label(root, textvariable=last, font=("Segoe UI", 9), fg="grey", wraplength=340,
             justify="left").pack(anchor="w", padx=8)
    bar = tk.Frame(root)
    bar.pack(side="bottom", fill="x", pady=4)
    paused = tk.BooleanVar(value=False)
    tk.Checkbutton(bar, text="Pause", variable=paused).pack(side="left", padx=8)
    tk.Button(bar, text="Quit", command=root.destroy).pack(side="right", padx=8)

    def alert(line: str):
        stamp = time.strftime("%H:%M:%S")
        print(f"[{stamp}] MENTION: {line}", flush=True)
        status.set(f"⚠ Mentioned at {stamp}")
        root.configure(bg="#c62828")
        beep()
        if args.speak:
            root.after(10, lambda: speak(f"{args.name[0]}, you were mentioned"))
        pop = tk.Toplevel(root)
        pop.title("You were mentioned!")
        pop.attributes("-topmost", True)
        tk.Label(pop, text=f"{stamp}\n{line}", font=("Segoe UI", 14), wraplength=500,
                 padx=20, pady=20).pack()
        tk.Button(pop, text="OK", command=lambda: (pop.destroy(), root.configure(bg="SystemButtonFace"
                  if sys.platform == "win32" else "#d9d9d9")), width=10).pack(pady=(0, 12))
        pop.lift()
        pop.focus_force()

    def tick():
        if not paused.get():
            try:
                text = ocr(grab(sct, region))
                if args.debug:
                    print("OCR:", text.replace("\n", " | "))
                tail = " ".join(text.split())
                last.set(tail[-120:])
                for line in find_mentions(text, args.name, args.threshold):
                    if dedupe.is_new(line):
                        alert(line)
            except Exception as exc:
                last.set(f"error: {exc}")
        root.after(int(args.interval * 1000), tick)

    root.after(200, tick)
    root.mainloop()


def main():
    p = argparse.ArgumentParser(description="Alert when your name appears in Teams captions.")
    p.add_argument("--name", action="append", help="Name to watch for (repeatable). Default: Keith")
    p.add_argument("--interval", type=float, default=1.0, help="Seconds between scans (default 1)")
    p.add_argument("--threshold", type=float, default=0.8, help="Fuzzy match 0-1 (default 0.8)")
    p.add_argument("--reselect", action="store_true", help="Draw a new caption region")
    p.add_argument("--speak", action="store_true", help="Also announce the alert (needs pyttsx3)")
    p.add_argument("--tesseract", help="Path to tesseract.exe if not on PATH")
    p.add_argument("--debug", action="store_true", help="Print OCR text every scan")
    args = p.parse_args()
    args.name = args.name or ["Keith"]

    if sys.platform == "win32":
        # Make screen coords match real pixels when Windows display scaling != 100%
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            pass
        default_exe = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
        if not args.tesseract and default_exe.exists():
            args.tesseract = str(default_exe)
    if args.tesseract:
        import pytesseract
        pytesseract.pytesseract.tesseract_cmd = args.tesseract

    cfg = json.loads(CONFIG_FILE.read_text()) if CONFIG_FILE.exists() else {}
    region = None if args.reselect else cfg.get("region")
    if not region:
        region = select_region()
        if not region:
            sys.exit("No region selected.")
        cfg["region"] = region
        CONFIG_FILE.write_text(json.dumps(cfg, indent=2))
    print(f"Region: {region}  |  watching for {args.name}  |  Ctrl+C or Quit to stop")
    run(args, region)


if __name__ == "__main__":
    main()
