from stockfish import Stockfish
import chess
import threading
import atexit
import os

_engine = None
_engine_lock = threading.Lock()
_current_depth = None


def _get_engine() -> Stockfish:
    """Lazily create the single, persistent Stockfish process."""
    global _engine
    if _engine is None:
        BASE_DIR = os.path.dirname(os.path.abspath(__file__))
        _engine = Stockfish(path=os.path.join(BASE_DIR, "..", "exe", "stockfish", "stockfish"))
        #_engine.update_engine_parameters({"Threads": 2, "Hash": 128})
    return _engine


def gen_move(fen: str, strength: int) -> dict:
    """Calculates the best chess move using a persistent Stockfish engine,
    and reports whether that move puts the opponent in check, checkmate,
    or stalemate.

    Reuses a single long-lived engine process instead of spawning a new
    one per call, to avoid repeated startup cost and memory pressure on
    low-RAM devices like the Pi Zero 2W.

    Stockfish itself is only used to pick the move; check/checkmate/
    stalemate detection is done with python-chess's rules engine (no
    extra engine process needed) by replaying the chosen move on a
    local board.

    Args:
        fen (str): The piece-placement field or partial FEN string
            representing the board position.
        strength (int): The search depth level to configure the Stockfish engine.

    Returns:
        dict | None: None if the input position already has no legal
            moves (e.g. the game was already over before this call).
            Otherwise a dict:
                {
                    "move": str,      # best move in UCI notation, e.g. "e2e4"
                    "status": str,    # "normal" | "check" | "checkmate" | "stalemate"
                    "new_fen": str,   # resulting FEN after the move
                }
    """
    global _current_depth, _engine

    with _engine_lock:
        engine = _get_engine()

        try:
            if _current_depth != strength:
                engine.set_depth(int(strength))
                _current_depth = strength

            engine.set_fen_position(fen)
            best_move = engine.get_best_move_time(6000)

            if best_move is None:
                # Engine responded but found nothing (e.g. mate/stalemate) —
                # not a crash, just no move to make.
                return None

        except Exception:
            # If the underlying process died (crash, OOM-kill, etc.),
            # drop the reference so the next call spins up a fresh one
            # instead of repeatedly hitting a dead process.
            _engine = None
            raise

    # Rules-based status check happens outside the engine lock — it only
    # touches python-chess's local board, not the Stockfish process, so
    # there's no need to hold the lock while doing it.
    board = chess.Board(fen)
    board.push_uci(best_move)

    if board.is_checkmate():
        status = "checkmate"
    elif board.is_check():
        status = "check"
    elif board.is_stalemate():
        status = "stalemate"
    else:
        status = "normal"

    return {
        "move": best_move,
        "status": status,
        "new_fen": board.fen(),
    }


def shutdown_engine():
    """Cleanly terminate the persistent Stockfish process, if running."""
    global _engine
    with _engine_lock:
        if _engine is not None:
            try:
                _engine.send_quit_command()
            except Exception:
                pass
            _engine = None


atexit.register(shutdown_engine)
