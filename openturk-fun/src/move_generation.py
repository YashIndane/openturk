from stockfish import Stockfish


def gen_move(fen: str, strength: int) -> str:
    """Calculates the best chess move using the Stockfish engine for White player

    Initializes Stockfish with a given search depth, extracts the active 
    player's turn to build a complete fallback FEN record, and evaluates the 
    position for up to 5 seconds to determine the optimal move.

    Args:
        fen (str): The piece-placement field or partial FEN string representing 
            the board position.
        player (str): The current player whose turn it is to move (e.g., 'white' 
            or 'black').
        strength (int): The search depth level to configure the Stockfish engine.

    Returns:
        str: The best calculated move in standard UCI notation (e.g., 'e2e4').
    """
    # 1. Safely initialize the engine process for this calculation
    stockfish = Stockfish(path="exe/stockfish/stockfish-ubuntu-x86-64-avx2")

    stockfish.set_depth(int(strength))
    
    # 2. Pass it to the engine safely
    stockfish.set_fen_position(fen)

    # 3. Generate the move
    best_move = stockfish.get_best_move_time(5000)
    
    return best_move
