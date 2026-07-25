from stockfish import Stockfish
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
        _engine.update_engine_parameters({"Threads": 2, "Hash": 16})
    return _engine


def gen_move(fen: str, strength: int) -> str:
    """Calculates the best chess move using a persistent Stockfish engine.

    Reuses a single long-lived engine process instead of spawning a new
    one per call, to avoid repeated startup cost and memory pressure on
    low-RAM devices like the Pi Zero 2W.

    Args:
        fen (str): The piece-placement field or partial FEN string
            representing the board position.
        strength (int): The search depth level to configure the Stockfish engine.

    Returns:
        str: The best calculated move in standard UCI notation (e.g., 'e2e4').
    """
    global _current_depth, _engine

    with _engine_lock:
        engine = _get_engine()

        try:
            if _current_depth != strength:
                engine.set_depth(int(strength))
                _current_depth = strength

            engine.set_fen_position(fen)
            best_move = engine.get_best_move_time(5000)

            if best_move is None:
                # Engine responded but found nothing (e.g. mate/stalemate) —
                # not a crash, just no move to make.
                return None

            return best_move

        except Exception:
            # If the underlying process died (crash, OOM-kill, etc.),
            # drop the reference so the next call spins up a fresh one
            # instead of repeatedly hitting a dead process.
            _engine = None
            raise


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