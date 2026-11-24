# Name Watcher – Teams caption alert

OCRs a screen region (Teams live captions) every second and alerts when your name appears.

## Setup (Windows)
1. Install Tesseract OCR: https://github.com/UB-Mannheim/tesseract/wiki (default path is auto-detected)
2. `pip install -r requirements.txt` (add `pyttsx3` for `--speak`)
3. In Teams: **More (…) → Language and speech → Turn on live captions**

## Run
```
python name_watcher.py              # first run: drag a box over the captions
python name_watcher.py --reselect   # redraw the box
python name_watcher.py --name Keith --name Murphy --speak
```

| Option | Default | Purpose |
|---|---|---|
| `--name` | Keith | Name(s) to watch, repeatable |
| `--interval` | 1.0 | Seconds between scans |
| `--threshold` | 0.8 | Fuzzy match strictness (catches OCR errors like `Kelth`, `Ke1th`) |
| `--speak` | off | Spoken alert via pyttsx3 |
| `--debug` | off | Print OCR text each scan |
| `--tesseract` | auto | Path to tesseract.exe |

Alert = 3 beeps + red status window + always-on-top popup with the caption line.
Each caption line alerts once (captions linger on screen for several seconds).
Region is saved to `~/.name_watcher.json`.

## Notes
- Keep the Teams window visible and un-minimised; the box must cover the caption area.
- A speaker *called* Keith will also trigger (their name label appears in the captions).
