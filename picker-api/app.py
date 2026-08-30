"""
This API runs on Rpi Zero

Run `iwconfig` — if `Power Management:on`, the Pi's WiFi radio may be sleeping between requests.
Disable with `sudo iw wlan0 set power_save off`.
"""

from flask import Flask, jsonify, request
from werkzeug.serving import WSGIRequestHandler
from chess_picker_4 import move_picker, shutdown

app = Flask(__name__)

@app.route('/drivepicker', methods=['GET'])
def drivepicker():
    # /drivepicker?move=e2ef&capture=yes/no
    move = request.args.get('move')
    capture = request.args.get('capture') == 'yes'

    try:
        move_picker(coor=move, capture=capture)
        #shutdown()
        # Return a success JSON response with HTTP 200 (default)
        return jsonify({
            'status': 'success',
            'message': 'Move executed successfully'
        }), 200

    except Exception as e:
        # Return an error JSON response with an HTTP 500 status code
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

if __name__ == '__main__':
    WSGIRequestHandler.address_string = lambda self: self.client_address[0]
    app.run(host='0.0.0.0', port=5000, debug=True, threaded=True)
