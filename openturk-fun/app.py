"""
OpenTurk — sample Flask app for local testing.

Serves the capture page and stubs out /analyse so you can test the
camera / flashlight / snap / retake flow end-to-end without a real
chess engine behind it.

Run:
    pip install flask pyopenssl
    python app.py

Then open the HTTPS URL it prints on your phone (same Wi-Fi as your
computer). HTTPS (or localhost) is required for getUserMedia and the
torch/flashlight API to work on a real device — plain http:// over
LAN will NOT get camera access.

(NOTE - This App is configured to play as `WHITE` Piece)
"""

import os
import argparse
from src.board_to_dict import generate_state_dictionary
from src.dict_to_fen import board_to_fen
from src.mov_o import gen_move
from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


@app.route("/")
def index():
    return render_template("capture_board.html")


@app.route("/analyse", methods=["POST"])
def analyse():
    image = request.files.get("image")
    perspective = request.form.get("perspective", "white")
    depth = request.form.get("depth", "1")

    if not image:
        return jsonify({"error": "No image received"}), 400

    # Save the capture so you can eyeball what the camera actually sent
    save_path = os.path.join(UPLOAD_DIR, "last_capture.png")
    image.save(save_path)
    size_kb = os.path.getsize(save_path) / 1024

    print(
        f"[analyse] got {size_kb:.1f} KB image | "
        f"perspective={perspective} | depth={depth}"
    )

    #Convert board to state dictionary
    board = generate_state_dictionary(openai_api_key=apikey)

    #Translate state dictionary to FEN notation
    fen_string = board_to_fen(board)
    
    print(fen_string)

    #Invoke StockFish for optimal move
    move = gen_move(fen_string, depth)

    print(move)

    return render_template("board.html", placement_dictionary=board, best_move=move)


def parseargs() -> None:
    """Parse command line arguments"""
    global apikey

    parser = argparse.ArgumentParser(
        add_help="Argument parser for Plate-fetcher"
    )

    parser.add_argument('--apikey', help="OpenAI API Key", required=True)
    args = parser.parse_args()
    apikey = args.apikey


if __name__ == "__main__":
    # ssl_context='adhoc' generates a throwaway self-signed cert so the
    # browser will grant camera/torch permissions over the network.
    # Your browser will show an "unsafe site" warning once — that's
    # expected for a self-signed cert, just proceed past it.
    parseargs()
    app.run(host="0.0.0.0", port=5000, debug=True, ssl_context="adhoc", use_reloader=False)
