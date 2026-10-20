# Fresh held-out set: deterministic scanner only (no AI)

Run on 2026-10-20 at commit `648a1e0`, the first scan of `bench/repos_fresh.json` after
`bench/FROZEN.md` froze the commit under test. Every clone matched its pinned commit. Counts
only: no per-item labels are published.

Strict rules come from the scanner's default settings. Leads come from `--inventory`.

| Repo | Items | Strict rules | Rule exceptions | Leads |
|---|---|---|---|---|
| fastapi/sqlmodel | 200 | 1 | 1 | 9 |
| fastapi-users/fastapi-users | 53 | 0 | 0 | 6 |
| wassim249/fastapi-langgraph-agent-production-ready-template | 29 | 0 | 0 | 4 |
| BetaStreetOmnis/xhs_ai_publisher | 33 | 0 | 0 | 0 |
| AhmadHassan-BTed/OpenOPC-Shadow-Adapter | 35 | 0 | 0 | 4 |
| insistence/RuoYi-FastAPI | 438 | 2 | 4 | 16 |
| slackapi/bolt-python | 64 | 0 | 0 | 2 |
| aegra/aegra | 162 | 3 | 6 | 8 |
| yezz123/authx | 103 | 1 | 1 | 4 |
| developmentseed/titiler | 109 | 0 | 0 | 0 |
| atpuxiner/fastapi-scaff | 19 | 0 | 0 | 4 |
| TheAlgorithms/Python | 62 | 0 | 0 | 0 |
| github/spec-kit | 1203 | 0 | 0 | 16 |
| nextlevelbuilder/ui-ux-pro-max-skill | 60 | 0 | 0 | 0 |
| Graphify-Labs/graphify | 54 | 0 | 0 | 3 |
| browser-use/browser-use | 125 | 1 | 1 | 4 |
| unclecode/crawl4ai | 107 | 0 | 0 | 6 |
| bytedance/deer-flow | 449 | 0 | 0 | 16 |
| hiyouga/LlamaFactory | 72 | 0 | 0 | 2 |
| headroomlabs-ai/headroom | not in the scan | | | |

Totals: 13 strict rule exceptions in 5 repos, and about 100 leads in the other 15. Five
repos produce no strict rule at all.

Parse warnings: `TheAlgorithms/Python` (6 files), `unclecode/crawl4ai` (1 file) and
`browser-use/browser-use` (1 file) contain Python that the scanner's Python 3.14 cannot read,
or invalid escape sequences. Their results may miss routes in those files.

## What this does not yet measure

- **Recall** needs planted bugs on these repos. None are planted yet.
- **Precision** needs the skill to be run on these repos and its BUG findings labelled by hand,
  blind to the arm, as `bench/PRECISION-LABELLING.md` describes. Neither has been done.
- **The real-bug set** (`bench/real_bugs.json`) was mined from fix commits in these same repos.
  Scanning HEAD can't find a bug that was already fixed there, so real-bug recall needs the
  parent commit of each fix. That is not yet set up.
