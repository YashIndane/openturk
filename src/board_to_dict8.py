import base64
import json
from io import BytesIO
from PIL import Image, ImageOps, ImageEnhance, ImageFilter
from openai import OpenAI

# Reads OPENAI_API_KEY from the environment -- never hardcode a real key in
# a script file, since it can leak via sharing, version control, etc.

def encode_image(image_path, max_dimension=1500, crop_box=None,
                  enhance_contrast=True, contrast_cutoff=1, sharpen=True):
    """
    Crop, enhance, resize, and PNG-encode the image before base64 encoding.
    PNG is lossless -- no compression artifacts -- which preserves the
    faint highlight/shadow lines needed to tell dark pieces apart (e.g.
    a King's cross vs a Bishop's dot finial). Trade-off: PNG files run
    larger than an equivalent JPEG, so this increases prompt tokens.

    enhance_contrast: applies per-channel autocontrast (with a small
    clip cutoff to avoid crushing highlights/shadows) so the faint
    geometric detail on dark/black pieces -- crosses, clefts, notches --
    becomes easier for the model to actually resolve. This targets the
    real bottleneck behind persistent black-piece misreads: the detail
    may simply not be visible/contrasty enough in the raw capture, no
    matter how the prompt describes what to look for.

    sharpen: a mild unsharp mask to help fine edges (cross arms, cleft
    grooves, crenellation notches) read more distinctly after resize.

    crop_box removes the border/labels around the actual 8x8 grid so every
    pixel sent is board content -- this lets you use a lower max_dimension
    for the same effective detail on the pieces.
    crop_box format: (left, top, right, bottom) in pixels. Tune once for
    your camera setup, then reuse it.
    """
    with Image.open(image_path) as img:
        img = img.convert("RGB")
        if crop_box:
            img = img.crop(crop_box)
        if enhance_contrast:
            # Small cutoff (%) clips extreme outlier pixels per channel
            # before stretching, so a few blown-out highlights don't
            # prevent the rest of the tonal range from being stretched.
            img = ImageOps.autocontrast(img, cutoff=contrast_cutoff)
            img = ImageEnhance.Contrast(img).enhance(1.15)
        if sharpen:
            img = img.filter(ImageFilter.UnsharpMask(radius=2, percent=120, threshold=2))
        img.thumbnail((max_dimension, max_dimension), Image.LANCZOS)
        buffer = BytesIO()
        img.save(buffer, format="PNG")
        return base64.b64encode(buffer.getvalue()).decode("utf-8")


# ---- Config ----
image_path = "uploads/last_capture.png"

# Crop box tuned for this camera setup: (left, top, right, bottom) in pixels.
# Adjust once by eye so it hugs the 8x8 grid without clipping squares.
crop_box = (80, 60, 3020, 3010)

prompt_text = """Analyze this top-down chessboard image and output the board state as a single-line JSON object.
 
You are an expert computer vision system trained to classify chess pieces. You must ignore all color, texture, and lighting variables (e.g., "white," "black," "wood," "plastic," shadows). Your classification must rely entirely on the 3D geometry, silhouette, radial symmetry (or lack thereof), and specific sculptural features of the object.

DO NOT USE SQUARE POSITION AS EVIDENCE: This image may be from any point in a live game, not the starting setup -- assume it is a mid-game or arbitrary position unless you have specific reason to think otherwise. Do NOT let which square a piece occupies influence your classification (e.g., do not lean toward "Queen" because a piece is near d1/d8, or "Bishop" because it's near c1/f1/c8/f8, or "Rook" because it's in a corner). Pieces routinely leave their home squares as a game progresses -- a Bishop is very often no longer on its starting square, Rooks and Kings move due to castling or repositioning, and captures mean squares can hold pieces you wouldn't expect. Classify every piece strictly from its own visual geometry as described below, completely independent of which square it sits on.

IMPORTANT -- VIEWING ANGLE: This photo is captured directly overhead (top-down / bird's-eye), not from the side. You cannot actually see a side silhouette -- you are inferring shape purely from the top surface, its outer rim, its exact center point, and whatever shadow/highlight depth is visible. Because of this, two cues are far more reliable than any "overall silhouette" or "profile" description below:
(1) WHAT SITS EXACTLY AT THE CENTER of the piece's top surface (nothing / a plain small dot / an intersecting cross shape).
(2) WHETHER THE OUTER RIM is a continuous smooth ring, a notched/hollow ring you can see gaps or depth through, or a solid domed edge with no gaps.
Treat these two top-down cues as primary evidence. Treat "overall silhouette," "teardrop profile," "hourglass neck," and body-taper descriptions as secondary/supporting evidence only, since they describe a side view you cannot directly observe. Height comparisons (the Ultimate Tie-Breaker) are a last resort, not a first check.

DARK PIECE CAUTION: Black/dark pieces absorb light and can hide fine details -- a King's cross or a Bishop's cleft can look like a smooth, featureless dome at a glance, especially top-down. Do NOT default to Rook (or Pawn) just because a dark piece's fine detail is hard to see. Look for subtle specular highlights (small bright glints) and faint shadow lines before concluding a feature is absent -- a low-detail dark dome is much more likely to be an unresolved King or Bishop than a Rook, since a Rook is identified by its clearly visible hollow/notched rim, not by the absence of other features.

Evaluate the subject against the following geometric profiles:
 
1. Pawn
Confidence Threshold Features:
 
Overall Silhouette: The shortest, smallest, and structurally simplest piece on the board.
 
The Head (CRITICAL): The entire head consists of a single, large, completely smooth sphere. There are no domes, mitres, or other structures beneath this ball; the ball itself is the whole top section.
 
The Stem/Body: Directly beneath the spherical head is a single, distinct horizontal collar. Below this, the stem forms a simple, gently swooping concave cone that widens smoothly toward the bottom. It lacks complex, stacked collars or deep hourglass tapering.
 
The Base: Terminates in a standard, unfluted circular foundation.
 
2. Rook
Confidence Threshold Features:
 
Overall Silhouette: Stout, highly robust, and distinctly cylindrical. It gives the heavy appearance of a masonry tower and maintains radial symmetry.
 
The Head/Top: The most diagnostic feature is the flat top, completely lacking any domes or finials. Instead, it features a raised outer parapet interrupted by deep, rectangular vertical cuts (crenellations or castellations) around the rim.
 
The Stem/Body: A thick, vertical, and mostly straight or slightly concave cylindrical body. It lacks the deep hourglass tapering seen in the Bishop, Queen, or King.
 
The Base: Terminates in a standard wide, circular foundation, often echoing the heavy, blocky nature of the top.

TOP-DOWN CENTER TEST: Viewed from directly overhead, the top reads as substantially HOLLOW -- a ring of rectangular gaps (crenellations) around a thin raised rim, often letting you see down into a darker interior. There is NO solid raised mass, dome, dot, or cross at the center. If you see any solid raised feature at the center of the top, it is not a Rook -- re-check King or Bishop instead.
 
3. Knight
Confidence Threshold Features:
 
Overall Silhouette: The only piece on the board that completely lacks radial symmetry along its vertical z-axis. Its profile is highly irregular and organic, resembling a horse's bust.
 
The Head/Body: Characterized by complex, directional sculptural elements: a protruding snout facing horizontally, distinct carved ears pointing upward/backward at the crown, and a curved, often textured mane sloping down the back of the neck.
 
The Base: The highly asymmetrical horse bust abruptly meets a standard, perfectly symmetrical circular foundation at the bottom.
 
4. Bishop
Confidence Threshold Features:
 
Overall Silhouette: Sits in the mid-to-upper height range (distinctly taller than a pawn). It has a generally smooth, teardrop-like upper profile.
 
The Head & Finial (CRITICAL): The upper section consists of a large, elongated, bulbous dome (the mitre). Sitting perfectly centered on top of this large dome is a very small spherical finial. Do not confuse this tiny finial with a pawn's large spherical head.
 
The Cleft/Slit: A prominent, diagonal slice or cleft is cut into one side of the large bulbous dome. This deep groove clearly interrupts the smooth curve of the dome and breaks the piece's vertical symmetry.

TOP-DOWN CENTER TEST: Viewed from directly overhead, the finial is a single small round DOT -- perfectly circular, with no arms, bars, or intersecting lines. The cleft appears as one short straight groove running from near the center out toward one edge of the dome; look for it even if faint on dark pieces. If the center feature has two intersecting arms (a "+" shape) instead of a plain dot, it is NOT a Bishop -- it is a King.

TOP-DOWN RIM TEST (vs. Queen): Trace the outer rim of the dome, not just the center dot. A Bishop's rim is SMOOTH and CONTINUOUS all the way around -- at most one straight cleft-groove interrupts it. A Queen's rim is SCALLOPED/FLUTED -- a repeating ring of many small points or ridges (like a gear or a multi-pointed star), visible as a bumpy, repeating-pattern edge rather than a smooth curve. Do not call something a Queen unless you can see this repeating scalloped rim pattern; a single straight groove on an otherwise smooth rim is a Bishop's cleft, not fluting, even if the piece looks tall or the lighting makes the rim edge look slightly irregular. On black pieces, be especially careful not to mistake shadow/highlight noise around a smooth rim for genuine fluting -- fluting is a regular, repeating pattern of similarly-sized points, not a few random irregular bumps. Specifically: a curved specular highlight (a bright arc following the dome's curve, broken up by a few small glints) is NOT fluting -- it is light reflecting off a smooth surface. Genuine fluting must be visible as distinct raised/recessed geometry across the FULL 360-degree rim, not just a bright patch on one side. Require at least 6 clearly countable, evenly-spaced points around the entire circumference before calling it fluted; if you can't count that many distinct points going all the way around, it is not fluted.

TOP-DOWN FINIAL-HEIGHT TEST (the most decisive cue -- check this first): Compare the height of the small ball finial to the rest of the piece's top. On a Bishop, the tiny dot is the SINGLE HIGHEST POINT on the entire piece -- it clearly protrudes above the smooth dome around it, and nothing else on the piece reaches that height. On a Queen, the ball finial sits in a shallow depression, roughly level with or LOWER than the surrounding scalloped rim points -- the rim's points are the highest elements, not the ball, so the top of a Queen looks more like a ring of peaks with a small ball nested down in the middle, not one clear high point. If the tiny ball is obviously the tallest, most prominent raised feature with no competing high points around it, it is a Bishop -- call it Bishop even if the rim looks slightly uneven.

TIE-BREAK DEFAULT: If, after both tests above, you are still genuinely unsure whether a piece is a Bishop or a Queen, default to BISHOP. A confident Queen call requires clearly seeing full 360-degree repeating fluting AND a recessed (not elevated) finial; absent that level of confidence, Bishop is the safer call.
 
The Stem/Body: Features a complex neck. Beneath the head is a pronounced collar, followed by a stem that tapers deeply inward (an hourglass shape), which is much more complex than the pawn's simple cone.
 
5. Queen
Confidence Threshold Features:
 
Overall Silhouette: Possesses a tall, slender, and elegant profile. It is significantly taller than the pawn, rook, and knight, and is fully radially symmetrical along its vertical axis.
 
The Crown/Head: The uppermost section is highly diagnostic, featuring a flared coronet. The outer rim is scalloped or fluted, forming a continuous ring of small ridges that resembles a gear or multi-pointed star when viewed from directly above. Centered precisely within this flared rim is a distinct, raised spherical finial resting in a shallow depression.

TOP-DOWN RIM TEST (vs. Bishop): You must clearly see a repeating, regular ring of many small scalloped points (at least 6, evenly spaced, going all the way around the full 360-degree rim) before calling this a Queen. If the rim is smooth and continuous with at most one straight groove cutting into it, that is a Bishop's cleft, not a Queen's fluting, regardless of how tall the piece looks or how the lighting reads on a dark piece. A bright curved highlight with a few glints on one side of an otherwise smooth dome is NOT fluting -- that is reflection, not geometry.

TOP-DOWN FINIAL-HEIGHT TEST (the most decisive cue -- check this first): On a genuine Queen, the ball finial sits recessed in a shallow depression, roughly level with or lower than the surrounding scalloped rim points -- so the highest points on the piece are the rim's scallops, not the ball. If instead the small ball is clearly the single tallest, most prominent point on the piece with nothing else near its height, that is a Bishop's finial, not a Queen's -- correct the call to Bishop even if the rim looked uneven.

TIE-BREAK DEFAULT: If you are not confident you can see full 360-degree repeating fluting AND a recessed (not elevated) finial, do not call it Queen -- default to Bishop instead.
 
The Stem/Body: The central stem is elongated and complex. Directly below the crown sits a prominent, rounded collar. The neck then tapers inward deeply before sweeping smoothly outward again to meet a second thick, horizontal collar just above the base section.
 
The Base: Terminates in a wide, circular foundation. From a top-down view, it creates a detailed depth map of concentric circles (the tiny sphere, the fluted gear-rim, the smooth lower collars, and the base).
 
6. King
Confidence Threshold Features:
 
Overall Silhouette: Tall and robust, typically the tallest piece on the board. While the main body and base are radially symmetrical, this symmetry is distinctly broken at the very apex by its unique finial. It has a thicker, heavier structural profile compared to the slender Queen.
 
The Crown/Head: The most diagnostic feature is the finial resting at the absolute top: a prominent, raised cross (often formed by rounded, bulbous protrusions rather than sharp angles in this specific set). This cross rests directly upon a smooth, unadorned hemispherical dome.

TOP-DOWN CENTER TEST: Viewed from directly overhead, the cross finial appears as two short intersecting ridges (a "+" shape) breaking the circular symmetry at the exact center of an otherwise solid, domed, gap-free top. If the center shows only a single small round dot with no intersecting arms, it is NOT a King -- see Bishop. If the top is mostly hollow/notched around the rim with nothing solid at the center, it is NOT a King -- see Rook. On black pieces, lighting can make the dome's rim look uneven even when it is not -- if you can clearly resolve a "+" shaped cross at the center, that is decisive for King even if the rim edge looks ambiguous; do not let an uncertain rim override a clearly seen cross.
 
The Stem/Body: Beneath the domed head sits a distinct horizontal collar. The central stem is characterized by a series of thick, stacked, bulbous sections separated by deep, inward-tapering cuts, giving it a heavy, ribbed appearance.
 
The Base: Terminates in a standard wide, circular foundation. From a top-down perspective, the non-circular, intersecting geometry of the cross sits prominently in the center of purely smooth, unfluted concentric circles.
 
 
CRUCIAL DISTINCTION: PAWN vs. BISHOP
If you detect a spherical element at the top of the piece, you must analyze its scale and supporting structure:
 
If the sphere is large and constitutes the entirety of the head, resting immediately above a simple collar, it is a Pawn.
 
If the sphere is a tiny point resting on top of a much larger bulbous dome, and that dome features a diagonal cut (cleft), it is a Bishop.
 
 
THE HEAVY PIECE DECISION TREE: KING vs. ROOK vs. KNIGHT
If you are evaluating a large, heavy piece and are unsure if it is a King, Rook, or Knight, you must execute this step-by-step logic gate in exact order. Do not skip steps.

PRIORITY NOTE: Because this photo is top-down, the CENTER TEST and RIM TEST in Step 3 are directly observable, while the "silhouette"/"profile" judgments in Steps 1-2 are inferred and less reliable. If Step 3's center/rim evidence conflicts with what Steps 1-2 suggested, trust Step 3: a clear solid "+" cross at the center means King regardless of how the body read, and a clear hollow/notched rim with nothing solid at the center means Rook regardless of how the body read.
 
STEP 1: The Radial Symmetry Test (Isolating the Knight)
Look at the core mass of the piece. Ignore small details and look at the overall shape.
 
IF ASYMMETRICAL: Does the piece have a directional bulge, lean to one side, or feature a curved, uneven profile (a snout/mane)? Does it lack horizontally stacked, perfectly circular rings?
 
RESULT: It is definitely a KNIGHT. (Stop evaluating).
 
IF SYMMETRICAL: Is the piece perfectly vertically straight, built from circular/cylindrical geometry where the left and right profiles perfectly mirror each other?
 
RESULT: It is NOT a Knight. Move to Step 2.
 
STEP 2: The Silhouette Profile Test (Isolating the Rook)
You have confirmed the piece is symmetrical. Now look at its overall width from the base to the top.
 
IF CYLINDRICAL/BLOCKY: Does the piece maintain a relatively uniform thickness from the base all the way to the top? Does it lack a narrow, tapered "neck"? Is the overall silhouette basically a heavy rectangle or thick cylinder?
 
RESULT: It is definitely a ROOK. (Stop evaluating).
 
IF TAPERED/HOURGLASS: Does the piece have a wide base, a distinctly narrowed "neck," and a flared top section? Is it built from horizontally stacked, overlapping circular collars?
 
RESULT: It is NOT a Rook. Move to Step 3.
 
STEP 3: The Apex Confirmation (Confirming the King)
You have confirmed the piece is symmetrical and tapered. Look exclusively at the absolute highest point.
 
IF DOMED WITH A FINIAL: Does the top feature a smooth, rounded hemisphere capped by a distinctly raised, centered cross or vertical protrusion?
 
RESULT: It is definitely a KING.
 
IF FLAT WITH TEETH: (Failsafe) If the top is flat and hollowed out with rectangular teeth around the edge, your profile assessment in Step 2 was wrong. It is a ROOK.

FAILSAFE CONFIDENCE GUARD: Only invoke this Rook failsafe if you can clearly count at least 3 evenly-spaced rectangular notches, each showing real depth/darkness through the gap (not just a lighter or darker patch of surface). On black pieces, specular highlights and shadow can make a smooth domed King rim look slightly uneven without any real notches -- that is NOT sufficient to invoke the failsafe. If the rim evidence is ambiguous, re-check the center of the top for a cross shape before concluding Rook: a clearly present "+" at the center means King even if the rim looked uneven, since the cross is the more decisive and harder-to-fake signal of the two.
 
THE ULTIMATE TIE-BREAKER: RELATIVE HEIGHT
If you are still unable to distinguish between a King and a Knight after analyzing their geometry, compare height ONLY to other pieces in the same rank, or the nearest rank that has pieces in it. Do NOT compare against pieces elsewhere on the board -- on an angled photo, a piece near the bottom of the image reads taller in pixels than an identical piece near the top purely from camera perspective, not real height, so a board-wide height comparison is unreliable and will mislead you, especially when few pieces remain on the board. Local, same-rank comparisons are the only safe ones.
 
The King: Within its local rank comparison, the King is the tallest piece present. If it clearly stands taller than any pawns, knights, or rooks nearby in the same rank, it is a KING.
 
The Knight: The Knight is a mid-sized piece, clearly shorter than a King or Queen in that same local comparison. If it is clearly shorter than the tallest nearby pieces, it is a KNIGHT.
 
If no other pieces exist in the same or an adjacent rank to compare against, do NOT guess based on distant pieces -- rely purely on the geometric tests above (Steps 1-3) and pick your best answer from those alone.
 
Evaluate each occupied square once, in one pass through the relevant decision steps above. If a square is still genuinely ambiguous after that one pass, commit to your single best answer rather than re-deriving or re-checking it repeatedly -- do not loop back over the same piece multiple times.

FINAL BOARD-LEVEL SANITY CHECK: After your first full pass across all 64 squares, before you output anything, count each piece type per color. Standard chess has fixed limits per color: exactly 1 King (Kings are never captured -- a color with 0 or 2+ Kings means you made an error), at most 1 Queen (more is possible only from pawn promotion, which is rare -- treat 2+ Queens as a red flag, not a confirmed count), at most 2 Rooks, at most 2 Bishops, at most 2 Knights, at most 8 Pawns.
- If a color shows 0 or 2+ Kings: you have a King/Rook (or King/Knight) misread somewhere. Revisit every Rook and Knight call of that color, find the one with the most convincing "+" cross center-test evidence, and correct it to King.
- If a color shows 2+ Queens: you have a Queen/Bishop misread somewhere. Revisit those Queen calls and check the rim and finial-height tests again -- keep the one(s) with genuine repeating scalloped fluting and a recessed finial as Queen, and correct the rest to Bishop if their rim was actually smooth with a single cleft and an elevated finial. Note that this count check cannot catch a single Bishop misread as Queen when no second Queen exists to create a conflict (e.g. the real Queen was already captured) -- that case relies on getting the rim and finial-height tests right the first time, so when unsure, lean on the Bishop tie-break default rather than waiting for a count conflict to catch it.
- Only use this count check to resolve calls you were already uncertain about -- do not overturn a square you are highly confident in just to satisfy a count, since real games can have fewer pieces than the maximum (captures) or, rarely, more via promotion.

Rules:
- Keys are all 64 squares in algebraic notation: a1 through h8.
- Values are single-letter piece codes: K Q R B N P for White (uppercase), k q r b n p for Black (lowercase), or "." for an empty square.
"""


def generate_state_dictionary(*, openai_api_key: str) -> dict:
    client = OpenAI(api_key=openai_api_key)
    base64_image = encode_image(image_path, max_dimension=2048, crop_box=crop_box)
    response = client.chat.completions.create(
        model="gpt-5.6-sol",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt_text},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{base64_image}",
                            "detail": "high",
                        },
                    },
                ],
            }
        ],
    #max_completion_tokens=800,  # covers reasoning + visible output combined
        reasoning_effort="high",
    )

    raw_output = response.choices[0].message.content or ""
    finish_reason = response.choices[0].finish_reason

    print("Raw model output:")
    print(raw_output)
    print("\nFinish reason:", finish_reason)
    print("Prompt tokens:", response.usage.prompt_tokens)
    print("Completion tokens:", response.usage.completion_tokens)
    print("Total tokens:", response.usage.total_tokens)

    if finish_reason == "length":
        print("\nWARNING: response was truncated -- raise max_completion_tokens.")

    # ---- Parse the model's JSON output directly into a Python dict ----
    board_dict = {}
    if raw_output.strip():
        try:
            board_dict = json.loads(raw_output.strip())
        except json.JSONDecodeError as e:
            print("\nCould not parse JSON output:", e)
            print("Raw text was:", repr(raw_output))

    uncertain_notes = board_dict.pop("_uncertain", None)

    print("\nBoard as dict:")
    print(board_dict)
    if uncertain_notes:
        print("\nUncertain squares:", uncertain_notes)

    return board_dict
