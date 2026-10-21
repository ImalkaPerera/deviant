# Recording the demo

How to record the two short clips for the README: the scan in a terminal, and the Claude Code
skill judging and reviewing. Both use the same demo project, so they tell one story.

## 1. Build the demo project

```bash
python docs/demo/make_demo_project.py ~/deviant-demo
```

It writes a FastAPI project with 48 routes and real git history. Ann writes 47 routes, each with
an auth dependency. Dana then adds `GET /users/export` without one, in a commit named
`add csv export`. Two more bugs are planted for the skill to find by reading the code:

| Bug | Where | Found by |
|---|---|---|
| A CSV export of every user with no auth | `app/routes/items.py`, `export_users_csv` | the scan (47 of 48 routes have auth) |
| A release step that ignores its failure | `.github/workflows/release.yml`, `publish` | the scan's inventory |
| A 404 raised when the item *is* found | `app/routes/items.py`, `item_owner` | the skill's review step |

## 2. The terminal clip (about 10 seconds)

Use a dark theme, a large font (18 to 20 pt) and a window about 100 columns by 20 rows.

```bash
cd ~/deviant-demo
deviant-scan . --with-git
```

Hold on the output for three seconds, so a viewer can read `n=48 s=47 v=1` and
`same author wrote 0 of the 47 compliant items checked`.

To record it as a GIF without editing, [VHS](https://github.com/charmbracelet/vhs) can play
`docs/demo/scan.tape`:

```bash
vhs docs/demo/scan.tape   # writes docs/assets/demo-scan.gif
```

Or render it from the real output with Pillow, which is how `docs/assets/demo-scan.gif` was made:

```bash
cd ~/deviant-demo && deviant-scan . --with-git --color always > /tmp/scan.ansi && cd -
python docs/demo/render_gif.py /tmp/scan.ansi "deviant-scan . --with-git" "~/deviant-demo $ " \
  docs/assets/demo-scan.gif
```

## 3. The Claude Code clip (about 20 seconds, sped up)

Install the plugin once, then open Claude Code in the demo project:

```text
/plugin install deviant --marketplace ImalkaPerera/deviant
/deviant:deviant .
```

Record the screen with any recorder, then speed up the middle (the skill reads files for about a
minute) so the clip is under 25 seconds. End on the report table. The first three rows should be
the three bugs above, labelled BUG, each with its proof. Later rows vary from run to run.

Keep the GIF under 5 MB so GitHub shows it inline. `gifski --fps 12 --width 1200` or an
`ffmpeg` palette pass usually gets there.

## 4. Put it in the README

The terminal clip is already at the top of `README.md` as `docs/assets/demo-scan.gif`. When the
Claude Code clip is ready, save it as `docs/assets/demo-skill.gif`, put it at the top in place of
the terminal clip, and move the terminal clip under "Quick start". Write alt text that says what
the clip shows, as the current one does.
