def board_to_fen(board, active_color='w', castling='-',
                  en_passant='-', halfmove_clock=0, fullmove_number=1):
    """
    Convert a chess board dict to a FEN string.

    board: dict like {'a1': 'R', 'b1': 'N', ..., 'e4': '.'}
           keys = square names (e.g. 'a1'..'h8')
           values = one of 'PNBRQK' (white), 'pnbrqk' (black), or '.' / '' / None for empty

    Returns full FEN string, e.g.:
    'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w - - 0 1'
    """
    files = 'abcdefgh'
    ranks = '87654321'  # FEN goes rank 8 -> rank 1
    valid_pieces = set('PNBRQKpnbrqk')

    fen_rows = []
    for rank in ranks:
        empty_count = 0
        row_fen = ''
        for file in files:
            square = f'{file}{rank}'
            piece = board.get(square, '.')

            if piece is None or piece == '' or piece == '.':
                empty_count += 1
                continue

            if piece not in valid_pieces:
                raise ValueError(
                    f"Invalid piece '{piece}' at square '{square}'. "
                    f"Expected one of {sorted(valid_pieces)} or '.' for empty."
                )

            if empty_count > 0:
                row_fen += str(empty_count)
                empty_count = 0
            row_fen += piece

        if empty_count > 0:
            row_fen += str(empty_count)

        fen_rows.append(row_fen)

    piece_placement = '/'.join(fen_rows)

    # --- basic sanity checks ---
    if active_color not in ('w', 'b'):
        raise ValueError("active_color must be 'w' or 'b'")

    white_kings = sum(row.count('K') for row in fen_rows)
    black_kings = sum(row.count('k') for row in fen_rows)
    if white_kings != 1 or black_kings != 1:
        raise ValueError(
            f"Expected exactly one king per side, found "
            f"white={white_kings}, black={black_kings}"
        )

    fen = f"{piece_placement} {active_color} {castling} {en_passant} {halfmove_clock} {fullmove_number}"
    return fen