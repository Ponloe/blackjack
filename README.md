# Blackjack Card Counting Trainer

Local laptop practice tool, implemented in verified milestones. This repository
now includes the **local dashboard, saved event-sourced sessions, manual entry,
live counts and recommendations, and webcam/video previews**, in addition to
the verified core and simulator. The frontend is plain HTML, CSS, and vanilla
JavaScript served by FastAPI. No Node, React, build step, account, or hosting.
**Camera previews do not recognize or automatically count ranks yet.**
The repository root is the project root (no extra nested directory is needed).

## Setup and verification

Requires Python 3.11 or newer. From this directory:

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app
```

Open **http://localhost:8000**. Keep the terminal running; Ctrl+C stops the server.
Use one server worker so every browser tab shares the same session and webcam.
To verify the application:

```sh
python -m pytest -q
```

The current fast suite passes **152 tests**. With the server running, an
additional read-only HTTP/WebSocket smoke check is available:
`python scripts/check_server.py`.

The default test run excludes the million-round Monte Carlo check. Run that
explicitly with `python -m pytest -q -m slow`, or run every test with
`python -m pytest -q -m 'slow or not slow'`.

## Using the dashboard

1. Choose the card source and click a rank (or type A, 2–9, 0/T, J, Q, K).
2. Enter your two cards and the dealer up-card to see a recommendation.
   Recommendations assume the dealer has already checked for blackjack.
3. Count other exposed cards using the Other source. Enter a dealer hole card
   only after it is revealed; use Dealer revealed cards for subsequent draws.
4. Next hand clears the displayed hands while preserving the shoe count.
   New shoe resets the count. Undo reverses the most recent event, including
   New hand, New shoe, removal, or correction. U undoes; N starts a new hand.
5. Fix in Recent cards corrects rank, source, or hand ID in a single undoable
   event without counting a card twice. Remove subtracts a mistaken entry.
6. Apply table rules to update recommendations and count rounding. Changing
   the number of decks starts a fresh shoe; Undo restores the previous shoe
   and its deck count. Other rule edits are settings, not undoable card events.

The hand selector supports up to four player hands. For a split, Fix one card
to move it to a different hand ID, mark both hands From a split, and enter
their drawn cards using the appropriate hand selector. Other players can have
separate hand IDs as well. Naturals on split hands are not paid as blackjacks.

State changes are delivered over `/ws`; there is no state polling. The page
reconnects automatically and disables card entry while disconnected. SQLite
persists the event log and configuration in `data/session.sqlite3`. Restarting
the server or refreshing the page restores the session. Camera frames and
recorded videos are never saved to the database. Set `BLACKJACK_DB` to use a
different database file for an independent session.

## Webcam and recorded video

**Browser webcam (recommended):** click Enable webcam and allow the browser's
camera prompt. This preview stays in the browser, requests no microphone,
and does not upload or record video. Once permission is granted, the webcam
selector lists available devices. Stop preview or close the tab to release it.
Camera activation is always explicit; opening the dashboard does not open it.

**OpenCV webcam:** choose OpenCV webcam, select its numeric index (usually 0),
then Start preview. A background Python thread captures the camera and serves
an MJPEG preview at `/video_feed`. Green outlines indicate card-shaped objects,
not recognized ranks. The detector uses grayscale, blur, adaptive threshold,
convex quadrilaterals, aspect-ratio filtering, and 200×300 perspective warps.
Use Stop preview to release this shared camera, or stop the server. Unlike the
browser preview, closing one tab does not stop an OpenCV camera shared by
other tabs. Browser and OpenCV modes should not open the same webcam together.

**Recorded video:** choose Recorded video and select a browser-compatible MP4
or WebM. It plays locally with pause/seek controls and is never uploaded. To
exercise the OpenCV pipeline against a local file instead:

```sh
python -m app.run --video path/to/practice.mp4
```

Then choose OpenCV webcam and Start preview; the configured file replaces the
camera input. Playback stops at the end; Start preview replays it. The equivalent
environment variable is `BLACKJACK_VIDEO` when using the usual uvicorn command.

If camera access fails:

- Open `http://localhost:8000`, not the HTML file directly or a LAN HTTP address.
- Allow camera access in the browser's site settings and your OS privacy settings.
  On macOS, check System Settings → Privacy & Security → Camera. Browser mode
  needs the browser's permission; OpenCV mode needs the terminal/Python launcher's.
- Close other apps using the camera. Try Default webcam or another OpenCV index.
- Prefer a regular Chrome, Edge, Firefox, or Safari window if an embedded browser
  does not expose camera permission prompts.

Verification covers capture start/stop, unavailable cameras, JPEG encoding,
status broadcasts, a synthetic card shape, and a real OpenCV recorded-video
fixture. **Physical webcam access and visual browser rendering still require a
check on your laptop; the automated browser connection was unavailable in the
development session.** Webcam permission cannot be granted by the app itself.

## Local API

The API is local-only, rejects foreign browser origins, and serves no external
scripts, fonts, or assets. It follows FastAPI's
[WebSocket](https://fastapi.tiangolo.com/advanced/websockets/) and
[static-file](https://fastapi.tiangolo.com/tutorial/static-files/) interfaces;
OpenCV capture uses [VideoCapture](https://docs.opencv.org/4.10.0/d8/dfe/classcv_1_1VideoCapture.html).

| Endpoint | Purpose |
| --- | --- |
| `POST /api/card` | `{rank, source, hand_id?, from_split?, replaces?}`; replaces is the ID of a card to correct |
| `POST /api/remove-card` | `{card_id}` removes an exposed card |
| `POST /api/undo` | Pop the last event |
| `POST /api/new-hand` | Clear hands, retain shoe count |
| `POST /api/new-shoe` | Start a fresh shoe |
| `GET /api/session/state` | Full derived state |
| `PUT /api/config` | Partial rule/rounding update |
| `WS /ws` | Initial state, then full state after every change |
| `POST /api/camera/start` | `{index: 0}` explicitly opens OpenCV preview |
| `POST /api/camera/stop` | Release the OpenCV camera |
| `GET /video_feed` | MJPEG stream; returns 503 until the camera is started |

The SQLite log stores CardDealt, NewHand, NewShoe, and RemoveCard. A CardDealt
with `replaces` corrects an existing card while retaining its original round
and order. NewShoe may store a new deck count. Replay remains dependency-free
in `core/events.py`. Mutations are validated before an atomic database write.

Try the core interactively:

```sh
python -c 'from core.cards import Rank; from core.hand import Hand; from core.counting import running_count, true_count; from core.shoe import Shoe; cards = (Rank.ACE, Rank.SIX); h = Hand(cards); s = Shoe(6, cards); print("Total:", h.total, "Soft:", h.is_soft, "Running:", running_count(cards), "True:", true_count(running_count(cards), s.decks_remaining))'
```

## Core conventions

- `Rank` preserves individual ten-value ranks and supplies blackjack and Hi-Lo values.
- `Hand` is immutable. Aces take the highest non-busting total, or the minimum
  total when all combinations bust. Split hands cannot be natural blackjacks.
  Pairs use blackjack value, so J/K is splittable.
- `Shoe` tracks exposed ranks, rejects impossible inventories, and estimates decks
  remaining as unexposed cards divided by 52. Unseen dealer hole cards are not counted.
- True count supports `none`, `floor`, and `round`; nearest rounding breaks ties
  away from zero. An empty shoe returns `None` because division by zero is undefined.
- Core imports only the Python standard library. Tests include an exhaustive
  ace-assignment oracle exercised by Hypothesis and full-shoe count invariants.

## Strategy and simulation (step 2)

```sh
python -m simulation.run --decks 6 --hands 10000
python -m simulation.run --decks 6 --hands 10000 --h17 --surrender --no-das
python -m simulation.run --decks 6 --hands 10000000 --seed 20260921 --validate
```

Try a recommendation:

```sh
python -c 'from core.cards import Rank; from core.hand import Hand; from core.strategy import Strategy; print(Strategy().recommend(Hand((Rank.EIGHT, Rank.EIGHT)), Rank.TEN))'
```

This prints `SPLIT`. Recommendations for an incomplete hand, a bust, or 21
return `None`. Callers resolve dealer blackjack before requesting a decision
and track already-completed hands and the one-card restriction on split aces.

`data/basic_strategy.json` defines all eight combinations of S17/H17, DAS/no
DAS, and late surrender/no surrender. Tables use explicit inheritance and cell
overrides to keep rule differences reviewable. Dealer J/Q/K use the 10 column.
The lookup engine enforces action eligibility; double-to-hit, double-to-stand,
and surrender fallbacks are in the JSON. When splitting is unavailable it
looks up the hand's hard/soft total. Table loading rejects missing rows,
unknown codes, missing fallbacks, and inheritance cycles.

The supported strategy is **total-dependent American peek blackjack with 4–8
decks**. One-, two-, and three-deck strategy tables are not included and those
configurations are rejected instead of receiving a shoe-game recommendation.
The lower-level `Shoe` from step 1 still accepts any positive number of decks.

Rules and simulator conventions:

- Defaults: six decks, stand on soft 17, double after split, no surrender,
  75% penetration. `RuleConfig` supplies the shared typed configuration.
- Naturals pay 3:2; dealer blackjack is checked before player decisions;
  doubling is on the first two cards only; no insurance.
- Split to at most four hands, with no resplitting aces and exactly one card
  on each split ace. Split 21 pays 1:1, not the natural payout.
- Cards are shuffled with a local seeded RNG and dealt without replacement.
  The cut card triggers a shuffle between rounds, never during one. A
  conservative card reserve can trigger an earlier shuffle at deep penetration
  so every round can finish. Requested penetration is accepted in `(0, 0.90]`.
- `--hands` counts initial rounds, **not** split hands. Flat bets start at one
  unit. Net profit includes additional split and double wagers. House edge is
  `-net_profit / initial_rounds`, not net loss divided by all money wagered.
- `--seed` makes runs reproducible; `--json` prints a machine-readable report
  to stdout. Progress goes to stderr every 100,000 rounds.

Strategy decisions were checked against Michael Shackleford's
[4–8 deck basic-strategy reference](https://wizardofodds.com/games/blackjack/strategy/4-decks/).
Tests also exercise scripted deals with independently specified payouts and
known decisions, rather than just comparing lookup outputs with JSON cells.

The simulator reports an approximate 95% confidence interval using **shoe
clusters**, which accounts for correlation among rounds in the same shoe.
A million hands still has substantial sampling uncertainty. `--validate`
requires at least one million rounds under the exact default rules and checks
whether the interval overlaps the requested 0.4–0.6% baseline. Passing means
statistical compatibility, **not proof** that the actual edge is inside that
band. H17, surrender, and no-DAS alter the expected edge, so this baseline check
does not apply to those settings. Unit tests, payout tests, and simulation
serve different purposes; an aggregate house-edge check alone cannot establish
that every strategy cell is optimal.

Verified result on Python 3.13.1, seed `20260921`: **10,000,000 initial rounds,
0.415675% house edge**, approximate 95% interval **0.344376%–0.486974%**.
The run took about 141 seconds on the development laptop. The point estimate
is in the requested band; the interval still expresses sampling uncertainty.
The initial one-million-round result was 0.1944% with a much wider interval,
so the same seeded simulation was extended to a fixed ten million rounds.
Both results, commands, and the strategy-file hash are recorded in
`simulation/validation.json`. These overlapping runs are not independent
replications. Verification: **137 fast tests and one million-round test passed**.

Count-accuracy metrics and decision statistics remain step 5. The simulator
currently validates basic-strategy outcomes only; it does not vary wagers or
apply count-based strategy deviations.

## Remaining milestones

5. Simulator count-accuracy and decision statistics.
7. Replaceable template classifier and calibration script.
8. Tracking, zones, commit deduplication, and pending confirmations.
9. Physical webcam validation with your camera and calibrated deck.

Camera preview and recorded-video support were added with the dashboard at
your request, after verification of the manual API and the prior simulator.
Rank classification, automatic counting, drawn source zones, and a pending
detection queue are not implemented in this milestone.
