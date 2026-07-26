import base64
import json
from io import BytesIO
from PIL import Image
from openai import OpenAI

# Reads OPENAI_API_KEY from the environment -- never hardcode a real key in
# a script file, since it can leak via sharing, version control, etc.

def encode_image(image_path, max_dimension=1350, quality=88, crop_box=None):
    """
    Crop, resize, and JPEG-compress the image before base64 encoding.
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
        img.thumbnail((max_dimension, max_dimension), Image.LANCZOS)
        buffer = BytesIO()
        img.save(buffer, format="JPEG", quality=quality)
        return base64.b64encode(buffer.getvalue()).decode("utf-8")


# ---- Config ----
image_path = "uploads/last_capture.png"

# Crop box tuned for this camera setup: (left, top, right, bottom) in pixels.
# Adjust once by eye so it hugs the 8x8 grid without clipping squares.
crop_box = (80, 60, 3020, 3010)

prompt_text = """Analyze this top-down chessboard image and output the board state as a single-line JSON object.
 
You are an expert computer vision system trained to classify chess pieces. You must ignore all color, texture, and lighting variables (e.g., "white," "black," "wood," "plastic," shadows). Your classification must rely entirely on the 3D geometry, silhouette, radial symmetry (or lack thereof), and specific sculptural features of the object.
 
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
 
The Stem/Body: Features a complex neck. Beneath the head is a pronounced collar, followed by a stem that tapers deeply inward (an hourglass shape), which is much more complex than the pawn's simple cone.
 
5. Queen
Confidence Threshold Features:
 
Overall Silhouette: Possesses a tall, slender, and elegant profile. It is significantly taller than the pawn, rook, and knight, and is fully radially symmetrical along its vertical axis.
 
The Crown/Head: The uppermost section is highly diagnostic, featuring a flared coronet. The outer rim is scalloped or fluted, forming a continuous ring of small ridges that resembles a gear or multi-pointed star when viewed from directly above. Centered precisely within this flared rim is a distinct, raised spherical finial resting in a shallow depression.
 
The Stem/Body: The central stem is elongated and complex. Directly below the crown sits a prominent, rounded collar. The neck then tapers inward deeply before sweeping smoothly outward again to meet a second thick, horizontal collar just above the base section.
 
The Base: Terminates in a wide, circular foundation. From a top-down view, it creates a detailed depth map of concentric circles (the tiny sphere, the fluted gear-rim, the smooth lower collars, and the base).
 
6. King
Confidence Threshold Features:
 
Overall Silhouette: Tall and robust, typically the tallest piece on the board. While the main body and base are radially symmetrical, this symmetry is distinctly broken at the very apex by its unique finial. It has a thicker, heavier structural profile compared to the slender Queen.
 
The Crown/Head: The most diagnostic feature is the finial resting at the absolute top: a prominent, raised cross (often formed by rounded, bulbous protrusions rather than sharp angles in this specific set). This cross rests directly upon a smooth, unadorned hemispherical dome.
 
The Stem/Body: Beneath the domed head sits a distinct horizontal collar. The central stem is characterized by a series of thick, stacked, bulbous sections separated by deep, inward-tapering cuts, giving it a heavy, ribbed appearance.
 
The Base: Terminates in a standard wide, circular foundation. From a top-down perspective, the non-circular, intersecting geometry of the cross sits prominently in the center of purely smooth, unfluted concentric circles.
 
 
CRUCIAL DISTINCTION: PAWN vs. BISHOP
If you detect a spherical element at the top of the piece, you must analyze its scale and supporting structure:
 
If the sphere is large and constitutes the entirety of the head, resting immediately above a simple collar, it is a Pawn.
 
If the sphere is a tiny point resting on top of a much larger bulbous dome, and that dome features a diagonal cut (cleft), it is a Bishop.
 
 
THE HEAVY PIECE DECISION TREE: KING vs. ROOK vs. KNIGHT
If you are evaluating a large, heavy piece and are unsure if it is a King, Rook, or Knight, you must execute this step-by-step logic gate in exact order. Do not skip steps.
 
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
 
THE ULTIMATE TIE-BREAKER: RELATIVE HEIGHT
If you are still unable to distinguish between a King and a Knight after analyzing their geometry, compare height ONLY to other pieces in the same rank, or the nearest rank that has pieces in it. Do NOT compare against pieces elsewhere on the board -- on an angled photo, a piece near the bottom of the image reads taller in pixels than an identical piece near the top purely from camera perspective, not real height, so a board-wide height comparison is unreliable and will mislead you, especially when few pieces remain on the board. Local, same-rank comparisons are the only safe ones.
 
The King: Within its local rank comparison, the King is the tallest piece present. If it clearly stands taller than any pawns, knights, or rooks nearby in the same rank, it is a KING.
 
The Knight: The Knight is a mid-sized piece, clearly shorter than a King or Queen in that same local comparison. If it is clearly shorter than the tallest nearby pieces, it is a KNIGHT.
 
If no other pieces exist in the same or an adjacent rank to compare against, do NOT guess based on distant pieces -- rely purely on the geometric tests above (Steps 1-3) and pick your best answer from those alone.
 
Evaluate each occupied square once, in one pass through the relevant decision steps above. If a square is still genuinely ambiguous after that one pass, commit to your single best answer rather than re-deriving or re-checking it repeatedly -- do not loop back over the same piece multiple times.
 
Rules:
- Keys are all 64 squares in algebraic notation: a1 through h8.
- Values are single-letter piece codes: K Q R B N P for White (uppercase), k q r b n p for Black (lowercase), or "." for an empty square.
"""


def generate_state_dictionary(*, openai_api_key: str) -> dict:
    client = OpenAI(api_key=openai_api_key)
    base64_image = encode_image(image_path, crop_box=crop_box)
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
                            "url": f"data:image/jpeg;base64,{base64_image}",
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
