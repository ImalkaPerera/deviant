"""Render a typed command and its real ANSI output as an animated terminal GIF.

Usage: python docs/demo/render_gif.py <ansi output file> <command> <prompt> <out.gif>

Needs Pillow and the DejaVu Sans Mono font. RECORDING.md shows how docs/assets/demo-scan.gif
was made with it.
"""

import re
import sys

from PIL import Image, ImageDraw, ImageFont

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"
SIZE = 22
PAD_X, PAD_Y, BAR = 28, 22, 40
COLS = 82

BG = (24, 26, 33)
BAR_BG = (36, 39, 48)
FG = (220, 223, 228)
DIM = (128, 134, 150)
GREEN = (126, 211, 135)
YELLOW = (240, 200, 110)
RED = (255, 107, 107)
PROMPT = (130, 170, 255)
DOTS = [(255, 95, 86), (255, 189, 46), (39, 201, 63)]

SGR = re.compile(r"\x1b\[([0-9;]*)m")


def spans(line):
    """[(text, colour, bold)] for one line of ANSI text."""
    out, colour, bold, pos = [], FG, False, 0
    for m in SGR.finditer(line):
        if m.start() > pos:
            out.append((line[pos : m.start()], colour, bold))
        codes = m.group(1).split(";")
        if codes == ["0"] or codes == [""]:
            colour, bold = FG, False
        for c in codes:
            if c == "1":
                bold = True
            elif c == "2":
                colour = DIM
            elif c == "31":
                colour = RED
            elif c == "32":
                colour = GREEN
            elif c == "33":
                colour = YELLOW
        pos = m.end()
    if pos < len(line):
        out.append((line[pos:], colour, bold))
    return out


def main(ansi_file, command, prompt, out):
    regular = ImageFont.truetype(FONT, SIZE)
    bold = ImageFont.truetype(BOLD, SIZE)
    cw = regular.getlength("M")
    lh = int(SIZE * 1.45)
    output = open(ansi_file, encoding="utf-8").read().rstrip("\n").splitlines()
    rows = len(output) + 3
    width = int(PAD_X * 2 + cw * COLS)
    height = BAR + PAD_Y * 2 + lh * rows

    def frame(typed, shown, cursor):
        img = Image.new("RGB", (width, height), BG)
        d = ImageDraw.Draw(img)
        d.rectangle([0, 0, width, BAR], fill=BAR_BG)
        for i, colour in enumerate(DOTS):
            x = 22 + i * 24
            d.ellipse([x - 7, BAR // 2 - 7, x + 7, BAR // 2 + 7], fill=colour)
        title = "deviant-scan"
        d.text(
            ((width - regular.getlength(title) * 0.8) / 2, 9),
            title,
            fill=DIM,
            font=ImageFont.truetype(FONT, int(SIZE * 0.8)),
        )
        y = BAR + PAD_Y
        x = PAD_X
        d.text((x, y), prompt, fill=PROMPT, font=bold)
        x += bold.getlength(prompt)
        d.text((x, y), typed, fill=FG, font=regular)
        if cursor and shown == 0:
            cx = x + regular.getlength(typed)
            d.rectangle([cx, y + 3, cx + cw - 2, y + lh - 6], fill=FG)
        y += lh
        for line in output[:shown]:
            x = PAD_X
            for text, colour, is_bold in spans(line):
                font = bold if is_bold else regular
                d.text((x, y), text, fill=colour, font=font)
                x += font.getlength(text)
            y += lh
        if shown == len(output):
            d.text((PAD_X, y + lh * 0), prompt, fill=PROMPT, font=bold)
            cx = PAD_X + bold.getlength(prompt)
            if cursor:
                d.rectangle([cx, y + 3, cx + cw - 2, y + lh - 6], fill=FG)
        return img

    frames, durations = [], []

    def add(img, ms):
        frames.append(img)
        durations.append(ms)

    add(frame("", 0, True), 700)
    for i in range(1, len(command) + 1):
        add(frame(command[:i], 0, True), 55)
    add(frame(command, 0, True), 450)
    add(frame(command, 0, False), 350)  # the scan runs
    for n in range(1, len(output) + 1):
        add(frame(command, n, False), 90)
    for _ in range(4):  # hold, with a blinking cursor
        add(frame(command, len(output), True), 600)
        add(frame(command, len(output), False), 600)
    add(frame(command, len(output), True), 1500)

    palette = frames[-1].quantize(colors=64, method=Image.Quantize.MEDIANCUT)
    frames = [f.quantize(palette=palette, dither=Image.Dither.NONE) for f in frames]
    frames[0].save(
        out,
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=0,
        optimize=True,
        disposal=1,
    )


if __name__ == "__main__":
    main(*sys.argv[1:5])
