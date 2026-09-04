"""
OpenTurk — sample Flask app for local testing.
(NOTE - This App is configured to play as `BLACK` Piece)
"""

import os
import time
import requests
import argparse
import threading
from src.board_to_dict import generate_state_dictionary
from src.dict_to_fen import board_to_fen
from src.move_generation2 import gen_move
import time
from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Shared state for the laptop-side board view. /analyse (called by the phone)
# writes to this; /board and /state (called by the laptop) read from it.
# The lock keeps updates safe since the app runs threaded.
state_lock = threading.Lock()
latest_state = {
    "placement_dictionary": {},
    "engine_move": None,
    "status": None,
    "com_tokens": None,
    "version": 0,
}

STARTING_POSITION = {
    "a8": "r", "b8": "n", "c8": "b", "d8": "q", "e8": "k", "f8": "b", "g8": "n", "h8": "r",
    "a7": "p", "b7": "p", "c7": "p", "d7": "p", "e7": "p", "f7": "p", "g7": "p", "h7": "p",
    "a2": "P", "b2": "P", "c2": "P", "d2": "P", "e2": "P", "f2": "P", "g2": "P", "h2": "P",
    "a1": "R", "b1": "N", "c1": "B", "d1": "Q", "e1": "K", "f1": "B", "g1": "N", "h1": "R",
}


@app.route("/")
def index():
    return render_template("capture_board_au8.html")


@app.route("/board")
def board():
    # Open this on the laptop. It server-renders whatever the last analysed
    # position was; the page then polls /state on its own to stay current.
    with state_lock:
        state = dict(latest_state)
    return render_template(
        "render_boardau.html",
        placement_dictionary=state["placement_dictionary"] or STARTING_POSITION,
        engine_move=state["engine_move"],
        status=state["status"],
        com_tokens=state["com_tokens"],
    )


@app.route("/state")
def state():
    with state_lock:
        payload = dict(latest_state)
    if not payload["placement_dictionary"]:
        payload["placement_dictionary"] = STARTING_POSITION
    return jsonify(payload)


@app.route("/analyse", methods=["POST"])
def analyse():
    global capture_flag, move
    image = request.files.get("image")
    depth = request.form.get("depth", "1")

    if not image:
        return jsonify({"error": "No image received"}), 400

    # Save the capture so you can eyeball what the camera actually sent
    save_path = os.path.join(UPLOAD_DIR, "last_capture.png")
    image.save(save_path)
    size_kb = os.path.getsize(save_path) / 1024

    print(
        f"[analyse] got {size_kb:.1f} KB image | "
        f"depth={depth}"
    )

    # Convert board to state dictionary
    com_tokens, board_dict = generate_state_dictionary(openai_api_key=apikey)

    # Translate state dictionary to FEN notation
    fen_string = board_to_fen(board_dict)
    print(fen_string)

    # Invoke StockFish for optimal move
    engine_move = gen_move(fen_string, depth)

    print(f"\nMove: {engine_move['move']}",
          f"Status: {engine_move['status']}",
          f"New FEN: {engine_move['new_fen']}\n",
          sep="\n",
    )

    # Publish the new state for the laptop-side /board page to pick up.
    with state_lock:
        latest_state["placement_dictionary"] = board_dict
        latest_state["engine_move"] = engine_move["move"]
        latest_state["status"] = engine_move["status"]
        latest_state["com_tokens"] = com_tokens
        latest_state["version"] += 1

    # Set move & capture flag
    capture_flag = engine_move['capture']
    move = engine_move['move']

    # Drive picker
    callpicker()

    # Wait for vibrations to settle down
    time.sleep(3)

    # Hand the phone the capture page back so it's ready for the next move.
    return render_template("capture_board_au8.html")


#@app.route('/callpicker', methods=['GET'])
def callpicker():
    try:
       cap = 'yes' if capture_flag else 'no'
       resp = requests.get(
           f'http://{picker_ip}:5000/drivepicker',
           params={'move':move, 'capture':cap},
           timeout=(15, 70),    #(connect_timeout, read_timeout)
       )
       resp.raise_for_status()
       return jsonify(resp.json()), resp.status_code

    except requests.exceptions.Timeout:
         return jsonify({'status':'error', 'message':'Drivepicker did not respond in time'}), 504
    except requests.exceptions.ConnectionError:
         return jsonify({'status':'error', 'message':'Could not reach picker'}), 502
    except requests.exceptions.HTTPError:
         return jsonify({'status':'error', 'message':f'Drivepicker returned {resp.status_code}:{resp.text}'}), 502
    except requests.exceptions.RequestException as e:
         return jsonify({'status':'error', 'message':str(e)}), 500


def parseargs() -> None:
    """Parse command line arguments"""
    global apikey
    global picker_ip

    parser = argparse.ArgumentParser(
        add_help="Argument parser for Openturk"
    )

    parser.add_argument('--apikey', help="OpenAI API Key", required=True)
    parser.add_argument('--pickerip', help="Picker IPV4", required=True)
    args = parser.parse_args()
    apikey = args.apikey
    picker_ip = args.pickerip


if __name__ == "__main__":
    # ssl_context='adhoc' generates a throwaway self-signed cert so the
    # browser will grant camera/torch permissions over the network.
    # Your browser will show an "unsafe site" warning once — that's
    # expected for a self-signed cert, just proceed past it.
    parseargs()
    app.run(host="0.0.0.0", port=5002, debug=True, ssl_context="adhoc", use_reloader=False, threaded=True)