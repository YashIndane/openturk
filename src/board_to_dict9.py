import base64
import json
import os
from io import BytesIO
from PIL import Image, ImageDraw
from openai import OpenAI

# Reads OPENAI_API_KEY from the environment -- never hardcode a real key in
# a script file, since it can leak via sharing, version control, etc.

# ===========================================================================
# WHAT CHANGED FROM board_to_dict7.py, AND WHY
# ===========================================================================
# Your two failures (bishop misread as king at b3, king misread as rook at
# e7) both trace back to the same root cause, and it isn't really the prompt
# wording -- it's resolution.
#
# When OpenAI's vision API gets "detail": "high" on a roughly-square image
# under 2048px (your 1500px board photo qualifies), it scales the image's
# SHORT side down to 768px before tiling -- regardless of whether you send
# it at 1500px or 3000px wide. Raising max_dimension in the old script does
# nothing for accuracy; the model never sees more than ~768x768 pixels of
# actual board content. Split across an 8x8 grid, that's ~96px per square,
# and the one detail that separates a king from a bishop from a rook is a
# ~10-20px cross/dot/notch sitting inside that. On dark pieces especially,
# that's often just not enough pixels to resolve reliably -- no amount of
# prompt wording fixes a feature that was never visible in the first place.
#
# On top of that, the old prompt's "sanity check" step told the model to
# recount kings and, if a color had 0, go find a Rook/Knight call to flip to
# King. That's a reasonable idea, but it has a blind spot this exact image
# hit: the bishop at b3 got misread as a king FIRST, which meant Black's
# king count already read as 1 by the time the check ran -- so the real
# king at e7 (misread as rook) never got flagged for a second look. A wrong
# King call elsewhere silently satisfied the King quota. That's also a big
# part of why reasoning tokens balloon in mid/endgame: the model is working
# through a very long, repetitive decision tree (the same center/rim/height
# tests are each stated three or four times across the prompt) for every
# remaining piece, without any of that extra reasoning buying back the
# pixels it doesn't have.
#
# This version fixes both things:
#   1. RESOLUTION: the board is split into 4 overlapping quadrants (16
#      squares each), each sent as its own image. Each quadrant image is
#      itself small enough that "detail: high" barely downscales it, so
#      each square gets several times the pixel budget it got before.
#      Kings and Queens (the rarest, highest-value, easiest-to-confuse
#      pieces) plus anything the model flags as unsure then get a SECOND,
#      even tighter zoomed crop of just that one piece -- at that point the
#      crop is close to the camera's native resolution, so the cross-vs-dot
#      question that was ambiguous at 96px/square is usually not ambiguous
#      at all up close.
#   2. PROMPT: the geometric cues are stated ONCE (not four times), the
#      side-view "silhouette" language is trimmed since it doesn't apply to
#      a top-down photo anyway, and the self-satisfying recount-and-correct
#      step is gone -- instead, king/queen counts are checked in Python
#      *after* verification and reported to you as a warning, never used to
#      silently overwrite a square the model was never asked to re-look at.
#
# Trade-off: this makes ~4 to ~12+ API calls per board read instead of 1
# (quadrants + verification), so it costs more and takes longer per read.
# Tune QUADRANT_REASONING_EFFORT / ZOOM_REASONING_EFFORT and the
# VERIFY_* switches below if you want to trade some of that accuracy back
# for speed/cost once you've confirmed this fixes your error rate.
# ===========================================================================

MODEL = "gpt-5.6-sol"

# ---- Config ----
image_path = "uploads/last_capture.png"

# crop_box hugs the 8x8 playing surface only -- no border, no coordinate
# labels -- in the ORIGINAL photo's pixel space: (left, top, right, bottom).
# IMPORTANT: this value is now load-bearing in a way it wasn't before -- it's
# used to compute every per-square zoom crop, not just to trim the border off
# one full-board image. Run save_grid_preview() after any camera/zoom change
# and open the output image; nudge these numbers until every label sits
# inside the correct square, all the way into the corners.
crop_box = (120, 120, 2877, 2877)

BOARD_SIZE = 8
FILES = "abcdefgh"

# Zoom-crop margins (in units of one square), for the single-piece
# verification pass. Pieces are tall and the photo is only roughly overhead,
# so a piece's head can visually sit a square or more "above" its own square
# -- the top margin needs to be generous or the finial gets cropped off.
ZOOM_TOP_MARGIN = 1.9
ZOOM_SIDE_MARGIN = 0.55
ZOOM_BOTTOM_MARGIN = 0.15

# Quadrant layout: 0-based, half-open (start, end) ranges over the 8x8 grid.
# rank index 0 = the row nearest the TOP of the photo (rank 8 in the sample
# photo this was tuned against -- flip this assumption if your camera setup
# has rank 1 at the top instead; save_grid_preview() will make that obvious).
QUADRANTS = [
    dict(name="NW", files=(0, 4), ranks=(0, 4)),
    dict(name="NE", files=(4, 8), ranks=(0, 4)),
    dict(name="SW", files=(0, 4), ranks=(4, 8)),
    dict(name="SE", files=(4, 8), ranks=(4, 8)),
]
# Extra context (in units of one square) pulled into each quadrant crop, so
# pieces aren't cut off right at the seam between quadrants and so the model
# can still make local same-rank height comparisons near the edges.
QUADRANT_SIDE_CONTEXT = 1.0
QUADRANT_TOP_CONTEXT = 1.9   # taller margin: a piece can lean into the row above
QUADRANT_BOTTOM_CONTEXT = 1.0

# Verification switches -- both default on, since kings/queens are rare
# (cheap to double-check) and are exactly the categories that got confused.
VERIFY_KINGS_AND_QUEENS = True
VERIFY_FLAGGED_UNCERTAIN = True

QUADRANT_REASONING_EFFORT = "medium"  # fewer pieces per call than before -> less needed
ZOOM_REASONING_EFFORT = "low"         # one piece, close-up -> should be an easy call


# ---------------------------------------------------------------------------
# Shared piece-geometry cues (stated ONCE, reused by every prompt below)
# ---------------------------------------------------------------------------
PIECE_CUES = """All pieces are photographed top-down. Judge shape from the TOP SURFACE --
side-view "silhouette" guesses are unreliable from this angle and should only
break a tie, never override what the top surface actually shows. Ignore
color and ignore which square a piece sits on -- this may be a mid/endgame
position, so a piece can legitimately be far from its starting square.

Check the exact CENTER of the top first, then the outer RIM:

- PAWN: one plain, fully smooth ball. Nothing else sits on it.
- ROOK: mostly HOLLOW on top -- a thin raised ring broken by several
  rectangular notches with real visible depth/shadow through them. Nothing
  solid or raised at the center.
- KNIGHT: not radially symmetric at all -- a horse's head/mane profile,
  facing one direction. Unmistakable once you check for symmetry; if
  asymmetric, stop here.
- BISHOP: a smooth, unbroken dome (at most one straight cleft groove on one
  side) topped by a single small round dot. That dot is clearly the single
  highest point on the piece.
- QUEEN: a dome ringed by many small, evenly-spaced points/scallops -- 6 or
  more, all the way around. A bright highlight or a couple of stray glints on
  an otherwise smooth dome does NOT count as fluting. The small ball at the
  center sits low, level with or below those points, not clearly above them.
- KING: a smooth dome with a raised "+" (two crossing bars) at the exact
  center -- not a single round dot, and not a hollow notched rim.

Bishop vs Queen -- the rim decides it: a smooth rim (one cleft at most) is a
Bishop; a full ring of 6+ distinct points is a Queen. If you're genuinely
unsure, answer Bishop -- it's far more common, and one stray highlight is
easily mistaken for fluting, especially on dark pieces.

King vs Rook vs Bishop on DARK pieces: dark plastic hides fine detail, so a
king's cross or a bishop's cleft/dot can look like a plain dark dome at a
glance. Before defaulting to Rook, look again for the "+" (King) or the small
dot (Bishop) -- but don't invent one either. A genuine Rook has clearly
visible notches with real shadow depth all the way around; if you can't find
at least 3 evenly-spaced notches like that, it isn't a Rook.

Last resort only, relative height: if you still can't call it, compare
height only to other pieces in this same crop's rows -- never to pieces
elsewhere on the board, since camera perspective makes that unreliable.
King/Queen read tallest, Knight/Bishop mid-height, Pawn shortest.

If a square is still genuinely a coin-flip after all of that, make your
single best call and move on -- don't re-derive it more than once."""


# ---------------------------------------------------------------------------
# Grid geometry
# ---------------------------------------------------------------------------
def cell_size(box):
    left, top, right, bottom = box
    return (right - left) / BOARD_SIZE, (bottom - top) / BOARD_SIZE


def square_name(file_idx, rank_idx):
    return f"{FILES[file_idx]}{BOARD_SIZE - rank_idx}"


def square_to_indices(square):
    file_idx = FILES.index(square[0])
    rank_idx = BOARD_SIZE - int(square[1:])
    return file_idx, rank_idx


def square_box(file_idx, rank_idx, box):
    left, top, _, _ = box
    cw, ch = cell_size(box)
    x0 = left + file_idx * cw
    y0 = top + rank_idx * ch
    return (x0, y0, x0 + cw, y0 + ch)


def clip_box(box, image_size):
    w, h = image_size
    x0, y0, x1, y1 = box
    return (max(0, x0), max(0, y0), min(w, x1), min(h, y1))


def quadrant_crop(full_img, box, quad):
    left, top, _, _ = box
    cw, ch = cell_size(box)
    f0, f1 = quad["files"]
    r0, r1 = quad["ranks"]
    x0 = left + f0 * cw - QUADRANT_SIDE_CONTEXT * cw
    x1 = left + f1 * cw + QUADRANT_SIDE_CONTEXT * cw
    y0 = top + r0 * ch - QUADRANT_TOP_CONTEXT * ch
    y1 = top + r1 * ch + QUADRANT_BOTTOM_CONTEXT * ch
    return full_img.crop(clip_box((x0, y0, x1, y1), full_img.size))


def piece_zoom_crop(full_img, box, file_idx, rank_idx):
    x0, y0, x1, y1 = square_box(file_idx, rank_idx, box)
    cw, ch = cell_size(box)
    zbox = (
        x0 - ZOOM_SIDE_MARGIN * cw,
        y0 - ZOOM_TOP_MARGIN * ch,
        x1 + ZOOM_SIDE_MARGIN * cw,
        y1 + ZOOM_BOTTOM_MARGIN * ch,
    )
    return full_img.crop(clip_box(zbox, full_img.size))


def save_grid_preview(path="grid_preview.png"):
    """
    Draws the 8x8 grid implied by crop_box over the original photo, with
    algebraic square labels, so you can eyeball whether crop_box is aligned
    before trusting the per-square zoom crops used for verification.

    Run this once whenever you change camera position/zoom/crop_box, open
    the saved file, and nudge crop_box until every label sits inside its own
    square, all the way into the corners (not just the middle -- that's
    where small crop_box errors show up most).
    """
    img = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(img)
    for r in range(BOARD_SIZE):
        for f in range(BOARD_SIZE):
            x0, y0, x1, y1 = square_box(f, r, crop_box)
            draw.rectangle((x0, y0, x1, y1), outline=(255, 0, 0), width=3)
            draw.text((x0 + 8, y0 + 8), square_name(f, r), fill=(255, 0, 0))
    img.save(path)
    print(f"Saved grid preview to {path} -- open it and check the corners.")


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------
def build_quadrant_prompt(quad):
    f0, f1 = quad["files"]
    r0, r1 = quad["ranks"]
    squares = [square_name(f, r) for r in range(r0, r1) for f in range(f0, f1)]
    squares_str = ", ".join(squares)
    return (
        "Analyze this cropped top-down photo of PART of a chessboard.\n\n"
        "The crop includes a margin of neighboring squares for context, but "
        f"you must only report on these {len(squares)} squares: {squares_str}.\n"
        "Ignore any piece whose square isn't in that list, even if part of "
        "it is visible in this crop.\n\n"
        f"{PIECE_CUES}\n\n"
        "Output a single-line JSON object with exactly two keys:\n"
        '- "board": one entry per square listed above (only those squares), '
        "value is a single letter piece code -- K Q R B N P for White "
        '(uppercase), k q r b n p for Black (lowercase), or "." for empty.\n'
        '- "uncertain": a list of square names (a subset of the ones above) '
        "you are genuinely not confident about. Use [] if none.\n"
        "No text outside the JSON."
    )


def build_zoom_prompt(square, color_hint):
    return (
        f"This is a tightly cropped, top-down photo of a single chess piece "
        f"on square {square}. It is a {color_hint} piece.\n\n"
        f"{PIECE_CUES}\n\n"
        'Output a single-line JSON object: {"piece_type": one of '
        '"king", "queen", "rook", "bishop", "knight", "pawn", '
        '"confident": true or false}. No text outside the JSON.'
    )


# ---------------------------------------------------------------------------
# API + parsing helpers
# ---------------------------------------------------------------------------
def encode_image_b64(img, max_dimension=1500):
    img = img.convert("RGB").copy()
    img.thumbnail((max_dimension, max_dimension), Image.LANCZOS)
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


def parse_json_object(raw):
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    return json.loads(text.strip())


def call_vision(client, image_b64, prompt_text, reasoning_effort):
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt_text},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{image_b64}",
                            "detail": "high",
                        },
                    },
                ],
            }
        ],
        # max_completion_tokens=800,  # covers reasoning + visible output combined
        reasoning_effort=reasoning_effort,
    )
    choice = response.choices[0]
    return choice.message.content or "", choice.finish_reason, response.usage


# ---------------------------------------------------------------------------
# Stage 1: quadrant passes
# ---------------------------------------------------------------------------
def run_quadrants(client, full_img, box, log):
    board = {}
    uncertain_all = []
    totals = {"prompt": 0, "completion": 0, "total": 0}

    for quad in QUADRANTS:
        crop = quadrant_crop(full_img, box, quad)
        b64 = encode_image_b64(crop, max_dimension=1024)
        prompt = build_quadrant_prompt(quad)
        raw, finish_reason, usage = call_vision(client, b64, prompt, QUADRANT_REASONING_EFFORT)

        log(f"[{quad['name']}] finish={finish_reason} "
            f"tokens(prompt/completion/total)={usage.prompt_tokens}/{usage.completion_tokens}/{usage.total_tokens}")
        if finish_reason == "length":
            log(f"[{quad['name']}] WARNING: response truncated -- raise max_completion_tokens if you set one.")
        totals["prompt"] += usage.prompt_tokens
        totals["completion"] += usage.completion_tokens
        totals["total"] += usage.total_tokens

        try:
            data = parse_json_object(raw)
        except json.JSONDecodeError as e:
            log(f"[{quad['name']}] could not parse JSON ({e}); raw: {raw!r}")
            continue

        board.update(data.get("board", {}) or {})
        uncertain_all.extend(data.get("uncertain", []) or [])

    return board, uncertain_all, totals


# ---------------------------------------------------------------------------
# Stage 2: zoomed single-piece verification
# ---------------------------------------------------------------------------
def run_verification(client, full_img, box, board, squares, log):
    totals = {"prompt": 0, "completion": 0, "total": 0}
    corrections = []
    letter_map = {"king": "k", "queen": "q", "rook": "r",
                  "bishop": "b", "knight": "n", "pawn": "p"}

    for square in squares:
        current = board.get(square)
        if not current or current == ".":
            continue  # nothing there to verify against

        color_hint = "white" if current.isupper() else "black"
        file_idx, rank_idx = square_to_indices(square)
        crop = piece_zoom_crop(full_img, box, file_idx, rank_idx)
        b64 = encode_image_b64(crop, max_dimension=2000)  # crop is already small; this is a no-op resize in practice
        prompt = build_zoom_prompt(square, color_hint)
        raw, finish_reason, usage = call_vision(client, b64, prompt, ZOOM_REASONING_EFFORT)

        totals["prompt"] += usage.prompt_tokens
        totals["completion"] += usage.completion_tokens
        totals["total"] += usage.total_tokens

        try:
            data = parse_json_object(raw)
        except json.JSONDecodeError as e:
            log(f"[verify {square}] could not parse JSON ({e}); raw: {raw!r}")
            continue

        letter = letter_map.get(str(data.get("piece_type", "")).strip().lower())
        if not letter:
            log(f"[verify {square}] unrecognized piece_type {data.get('piece_type')!r}, keeping {current}")
            continue

        new_code = letter.upper() if color_hint == "white" else letter
        confident = data.get("confident")
        log(f"[verify {square}] stage1={current} -> zoom={new_code} (confident={confident})")
        if new_code != current:
            corrections.append((square, current, new_code, confident))
            board[square] = new_code

    return board, corrections, totals


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
def generate_state_dictionary(*, openai_api_key: str) -> dict:
    client = OpenAI(api_key=openai_api_key)
    full_img = Image.open(image_path).convert("RGB")

    log_lines = []

    def log(msg):
        log_lines.append(msg)
        print(msg)

    board, uncertain, usage1 = run_quadrants(client, full_img, crop_box, log)

    to_verify = set()
    if VERIFY_FLAGGED_UNCERTAIN:
        to_verify.update(uncertain)
    if VERIFY_KINGS_AND_QUEENS:
        to_verify.update(sq for sq, code in board.items() if code in ("k", "K", "q", "Q"))
    to_verify = sorted(to_verify)

    log(f"\nVerifying {len(to_verify)} square(s) with zoomed crops: {to_verify}")
    board, corrections, usage2 = run_verification(client, full_img, crop_box, board, to_verify, log)

    total_tokens = usage1["total"] + usage2["total"]
    log(f"\nTotal tokens across all calls: {total_tokens} "
        f"(quadrants: {usage1['total']}, verification: {usage2['total']})")

    if corrections:
        log("Corrections made during verification:")
        for square, old, new, confident in corrections:
            log(f"  {square}: {old} -> {new} (model confident: {confident})")
    else:
        log("No corrections made during verification.")

    # ---- Board-level sanity check: reported to you, never auto-corrected.
    # (The old prompt let the model "fix" this itself in one pass; that's
    # what let the b3/e7 errors mask each other. Now it's just a signal for
    # you -- or for re-running verification on more squares -- not a rule
    # the model applies to silently overwrite a square it wasn't asked
    # to re-examine.)
    counts = {}
    for code in board.values():
        if code != ".":
            counts[code] = counts.get(code, 0) + 1
    for color, king_code in (("White", "K"), ("Black", "k")):
        n = counts.get(king_code, 0)
        if n != 1:
            log(f"WARNING: {color} shows {n} King(s) -- expected exactly 1. "
                f"Consider adding suspect Rook/Bishop/Knight squares of that "
                f"color to a manual verification pass.")
    for color, queen_code in (("White", "Q"), ("Black", "q")):
        n = counts.get(queen_code, 0)
        if n >= 2:
            log(f"NOTE: {color} shows {n} Queens -- possible via promotion, "
                f"but double-check if you don't expect one in this game.")

    print("\nBoard as dict:")
    print(board)
    return board
