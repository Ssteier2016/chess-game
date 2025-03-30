import os
import eventlet
eventlet.monkey_patch()  # Aplicar monkey patch primero
from flask import Flask, render_template, jsonify, request, session
from flask_socketio import SocketIO, emit, join_room, leave_room
import mercadopago
import sqlite3
import bcrypt
import json
import time
import colorsys
import chess
import chess.engine

# Configuración Inicial
app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'Ma730yIan')  # Cambia esto por una clave secreta fuerte
socketio = SocketIO(app, cors_allowed_origins="*")
# Ajusta la ruta a Stockfish según tu entorno (local o Render)
DATABASE_PATH = '/opt/render/project/src/users.db' if os.getenv('RENDER') else 'users.db'
sdk = mercadopago.SDK("TEST-7030946997237677-031704-0d76aa7f3f9dc1968b5eb9a39b79b306-320701222")  # Access Token
stockfish_path = "/opt/render/project/src/stockfish" if os.getenv('RENDER') else "./stockfish"
engine = chess.engine.SimpleEngine.popen_uci(stockfish_path)
# Variables Globales
sessions = {}  # Almacena sid -> username
players = {}  # {room: {sid: {'color': str, 'chosen_color': str, 'bet': int, 'enable_bet': bool}}}
games = {}  # {room: {'board': list, 'turn': str, 'time_white': float, 'time_black': float, 'last_move_time': float}}
online_players = {}  # Lista de jugadores en línea
available_players = {}  # {sid: {'username': str, 'chosen_color': str}}

def reset_board(room=None):  # Unificada y simplificada
    board = [
        ['r', 'n', 'b', 'q', 'k', 'b', 'n', 'r'],
        ['p', 'p', 'p', 'p', 'p', 'p', 'p', 'p'],
        ['.', '.', '.', '.', '.', '.', '.', '.'],
        ['.', '.', '.', '.', '.', '.', '.', '.'],
        ['.', '.', '.', '.', '.', '.', '.', '.'],
        ['.', '.', '.', '.', '.', '.', '.', '.'],
        ['P', 'P', 'P', 'P', 'P', 'P', 'P', 'P'],
        ['R', 'N', 'B', 'Q', 'K', 'B', 'N', 'R']
    ]
    return board, 'white'

def is_white(piece):
    return piece.isupper()

def is_black(piece):
    return piece.islower()

def is_valid_move(piece, start_row, start_col, end_row, end_col, board):
    target = board[end_row][end_col]
    if target != '.' and is_white(piece) == is_white(target):
        return False
    dx = abs(end_row - start_row)
    dy = abs(end_col - start_col)
    piece = piece.lower()
    if piece == 'p':
        direction = -1 if is_white(board[start_row][start_col]) else 1
        if start_col == end_col and board[end_row][end_col] == '.':
            if end_row == start_row + direction:
                return True
            if (start_row == 1 and direction == 1) or (start_row == 6 and direction == -1):
                if end_row == start_row + 2 * direction and board[start_row + direction][start_col] == '.':
                    return True
        if dx == 1 and dy == 1 and target != '.' and is_white(target) != is_white(board[start_row][start_col]):
            if end_row == start_row + direction:
                return True
        return False
    elif piece == 'r':
        if dx == 0 or dy == 0:
            return is_path_clear(start_row, start_col, end_row, end_col, board)
        return False
    elif piece == 'n':
        return (dx == 2 and dy == 1) or (dx == 1 and dy == 2)
    elif piece == 'b':
        if dx == dy:
            return is_path_clear(start_row, start_col, end_row, end_col, board)
        return False
    elif piece == 'q':
        if dx == 0 or dy == 0 or dx == dy:
            return is_path_clear(start_row, start_col, end_row, end_col, board)
        return False
    elif piece == 'k':
        return dx <= 1 and dy <= 1 and (dx > 0 or dy > 0)
    return False

def is_path_clear(start_row, start_col, end_row, end_col, board):
    if start_row == end_row:
        step = 1 if end_col > start_col else -1
        for col in range(start_col + step, end_col, step):
            if board[start_row][col] != '.':
                return False
    elif start_col == end_col:
        step = 1 if end_row > start_row else -1
        for row in range(start_row + step, end_row, step):
            if board[row][start_col] != '.':
                return False
    else:
        row_step = 1 if end_row > start_row else -1
        col_step = 1 if end_col > start_col else -1
        row, col = start_row + row_step, start_col + col_step
        while row != end_row and col != end_col:
            if board[row][col] != '.':
                return False
            row += row_step
            col += col_step
    return True

def is_in_check(board, color):
    king_position = None
    for row in range(8):
        for col in range(8):
            piece = board[row][col]
            if color == 'white' and piece == 'K':
                king_position = (row, col)
            elif color == 'black' and piece == 'k':
                king_position = (row, col)
    if king_position is None:
        return False
    king_row, king_col = king_position
    for row in range(8):
        for col in range(8):
            piece = board[row][col]
            if piece != '.' and ((color == 'white' and is_black(piece)) or (color == 'black' and is_white(piece))):
                if is_valid_move(piece, row, col, king_row, king_col, board):
                    return True
    return False

def is_checkmate(board, color):
    if not is_in_check(board, color):
        return False
    for start_row in range(8):
        for start_col in range(8):
            piece = board[start_row][start_col]
            if piece != '.' and (is_white(piece) if color == 'white' else is_black(piece)):
                for end_row in range(8):
                    for end_col in range(8):
                        if is_valid_move(piece, start_row, start_col, end_row, end_col, board):
                            temp_board = [row[:] for row in board]
                            temp_board[end_row][end_col] = piece
                            temp_board[start_row][start_col] = '.'
                            if not is_in_check(temp_board, color):
                                return False
    return True

def load_wallet(username):
    conn = sqlite3.connect(DATABASE_PATH)
    c = conn.cursor()
    c.execute('SELECT balance FROM wallets WHERE username = ?', (username,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else 0

def save_wallet(username, balance):
    conn = sqlite3.connect(DATABASE_PATH)
    c = conn.cursor()
    c.execute('INSERT OR REPLACE INTO wallets (username, balance) VALUES (?, ?)', (username, balance))
    conn.commit()
    conn.close()

def update_timer(room):
    if room in games and games[room]['time_white'] is not None:
        current_time = time.time()
        if games[room]['last_move_time']:
            elapsed = current_time - games[room]['last_move_time']
            if games[room]['turn'] == 'white':
                games[room]['time_white'] = max(0, games[room]['time_white'] - elapsed)
            else:
                games[room]['time_black'] = max(0, games[room]['time_black'] - elapsed)
        games[room]['last_move_time'] = current_time
        print(f"Actualizando temporizador en {room}: Blancas={games[room]['time_white']:.2f}, Negras={games[room]['time_black']:.2f}")
        socketio.emit('timer_update', {'time_white': games[room]['time_white'], 'time_black': games[room]['time_black']}, room=room)
        if games[room]['time_white'] <= 0:
            socketio.emit('game_over', {'message': '¡Tiempo agotado! Gana negras'}, room=room)
            if room in players:
                del players[room]
            if room in games:
                del games[room]
        elif games[room]['time_black'] <= 0:
            socketio.emit('game_over', {'message': '¡Tiempo agotado! Gana blancas'}, room=room)
            if room in players:
                del players[room]
            if room in games:
                del games[room]

def init_db():
    conn = sqlite3.connect(DATABASE_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password BLOB, avatar TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS saved_games (username TEXT, room TEXT, game_name TEXT, board TEXT, turn TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS wallets (username TEXT PRIMARY KEY, balance REAL DEFAULT 0)''')
    conn.commit()
    conn.close()

init_db()

# Rutas HTTP
@app.route('/deposit_request', methods=['POST'])
def deposit_request():
    if 'username' not in session:
        return jsonify({'error': 'No autenticado'}), 401
    data = request.get_json()
    amount = data.get('amount', 0)
    preference = {
        "items": [{"title": "Recarga PeonkinGame", "quantity": 1, "currency_id": "ARS", "unit_price": float(amount)}],
        "back_urls": {"success": "https://peonkingame.onrender.com", "failure": "https://peonkingame.onrender.com", "pending": "https://peonkingame.onrender.com"},
        "auto_return": "approved"
    }
    result = sdk.preference().create(preference)
    emit('deposit_url', {'preference_id': result['response']['id']}, to=request.sid)
    return jsonify({'success': True})

@app.route('/withdraw_request', methods=['POST'])
def withdraw_request():
    if 'username' not in session:
        return jsonify({'error': 'No autenticado'}), 401
    data = request.get_json()
    amount = data.get('amount', 0)
    username = session['username']
    current_balance = load_wallet(username)
    if current_balance >= amount:
        save_wallet(username, current_balance - amount)
        emit('withdraw_success', {'amount': amount}, to=request.sid)
        emit('wallet_update', {'balance': load_wallet(username)}, to=request.sid)
        return jsonify({'success': True})
    return jsonify({'error': 'Fondos insuficientes'}), 400

@app.route('/success')
def success():
    return jsonify({'status': 'success'})

@app.route('/failure')
def failure():
    return jsonify({'status': 'failure'})

@app.route('/pending')
def pending():
    return jsonify({'status': 'pending'})

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/register', methods=['POST'])
def register():
    username = request.form.get('username')
    password = request.form.get('password')
    avatar = request.files.get('avatar')  # Obtener el archivo subido
    if not username or not password:
        return jsonify({'error': 'Usuario y contraseña requeridos'}), 400
    hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
    avatar_path = '/static/default-avatar.png'
    if avatar:
        avatar_dir = os.path.join(app.root_path, 'static', 'avatars')
        if not os.path.exists(avatar_dir):
            os.makedirs(avatar_dir)
        avatar_filename = f"{username}_avatar{os.path.splitext(avatar.filename)[1]}"
        avatar_path = f"/static/avatars/{avatar_filename}"
        avatar.save(os.path.join(app.root_path, 'static', 'avatars', avatar_filename))
        print(f"Avatar guardado en: {avatar_path}")
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        c = conn.cursor()
        c.execute('INSERT INTO users (username, password, avatar) VALUES (?, ?, ?)', (username, hashed_password, avatar_path))
        c.execute('INSERT OR IGNORE INTO wallets (username, balance) VALUES (?, 0)', (username,))
        conn.commit()
        conn.close()
        session['username'] = username
        return jsonify({'success': True, 'username': username, 'avatar': avatar_path})
    except sqlite3.IntegrityError:
        return jsonify({'error': 'El usuario ya existe'}), 400

@app.route('/get_avatar')
def get_avatar():
    username = request.args.get('username')
    conn = sqlite3.connect(DATABASE_PATH)
    c = conn.cursor()
    c.execute('SELECT avatar FROM users WHERE username = ?', (username,))
    result = c.fetchone()
    conn.close()
    return jsonify({'avatar': result[0] if result else '/static/default-avatar.png'})

@socketio.on('login')
def on_login(data):
    sid = request.sid
    username = data['username']
    password = data['password']
    conn = sqlite3.connect(DATABASE_PATH)
    c = conn.cursor()
    c.execute('SELECT password, avatar FROM users WHERE username = ?', (username,))
    result = c.fetchone()
    conn.close()
    if result and bcrypt.checkpw(password.encode('utf-8'), result[0]):
        sessions[sid] = username
        session['username'] = username  # Sincronizar con Flask session
        avatar = result[1] or '/static/default-avatar.png'
        emit('login_success', {'username': username, 'avatar': avatar}, to=sid)
        online_players[sid] = {'username': username, 'avatar': avatar}
        socketio.emit('online_players_update', list(online_players.values()))
    else:
        emit('login_error', {'error': 'Usuario o contraseña incorrectos'}, to=sid)

# Eventos Socket.IO - Conexión y Desconexión
@socketio.on('connect')
def on_connect():
    sid = request.sid
    username = session.get('username') or sessions.get(sid)
    if username:
        sessions[sid] = username  # Asegurar que el SID esté asociado al username
        conn = sqlite3.connect(DATABASE_PATH)
        c = conn.cursor()
        c.execute('SELECT avatar FROM users WHERE username = ?', (username,))
        result = c.fetchone()
        avatar = result[0] if result else '/static/default-avatar.png'
        conn.close()
        online_players[sid] = {'username': username, 'avatar': avatar}
        socketio.emit('online_players_update', list(online_players.values()))
        emit('wallet_update', {'balance': load_wallet(username)}, to=sid)  # Enviar saldo al conectar
    print(f"Cliente conectado: {sid}")

@socketio.on('disconnect')
def on_disconnect():
    sid = request.sid
    if sid in available_players:
        del available_players[sid]
        socketio.emit('waitlist_update', {'players': [{'sid': s, 'username': info['username'], 'chosen_color': info['chosen_color']} for s, info in available_players.items()]})
    for room in list(players.keys()):
        if sid in players[room]:
            del players[room][sid]
            if not players[room]:
                del players[room]
                if room in games:
                    del games[room]
            else:
                socketio.emit('player_left', {'message': 'El oponente abandonó la partida'}, room=room)
            break
    if sid in online_players:
        del online_players[sid]
        socketio.emit('online_players_update', list(online_players.values()))
    if sid in sessions:
        del sessions[sid]
    print(f"Cliente desconectado: {sid}")

@socketio.on('join_user_room')
def on_join_user_room(data):
    username = data['username']
    join_room(username)

# Eventos Socket.IO - Juego
@socketio.on('join')
def on_join(data):
    room = data['room']
    sid = request.sid
    timer_minutes = int(data.get('timer', 0))
    chosen_color = data.get('color', '#FFFFFF')
    bet = int(data.get('bet', 0))
    enable_bet = data.get('enableBet', False)
    is_public = data.get('isPublic', True)
    view_cost = data.get('viewCost', 0) if not is_public else 0
    
    username = sessions.get(sid)
    if not username:
        emit('error', {'message': 'Debes iniciar sesión'}, to=sid)
        return

    print(f"Jugador {sid} intentando unirse a {room}. Apostar: {enable_bet}, Monto: {bet}")
    current_balance = load_wallet(username)
    if enable_bet and current_balance < bet:
        emit('error', {'message': 'Fondos insuficientes para la apuesta'}, to=sid)
        return

    join_room(room)

    if room not in players:
        players[room] = {}

    if len(players[room]) >= 2:
        if room in games:
            games[room]['is_public'] = is_public
            games[room]['view_cost'] = view_cost
        emit('error', {'message': 'La sala está llena'}, to=sid)
        leave_room(room)
        return

    players[room][sid] = {
        'color': 'white' if len(players[room]) == 0 else 'black',
        'chosen_color': chosen_color,
        'bet': bet,
        'enable_bet': enable_bet,
        'username': username
    }
    emit('color_assigned', {'color': players[room][sid]['color'], 'chosenColor': chosen_color}, to=sid)
    print(f"Jugador {sid} asignado a {room} como {players[room][sid]['color']}")

    if room not in games:
        board, turn = reset_board(room)
        games[room] = {
            'board': board,
            'turn': turn,
            'is_public': is_public,
            'view_cost': view_cost,
            'time_white': timer_minutes * 60 if timer_minutes > 0 else None,
            'time_black': timer_minutes * 60 if timer_minutes > 0 else None,
            'last_move_time': time.time() if timer_minutes > 0 else None,
            'bet': bet if enable_bet else 0
        }

    if len(players[room]) == 2:
        player1_sid, player2_sid = list(players[room].keys())
        p1_bet = players[room][player1_sid]['bet']
        p2_bet = players[room][player2_sid]['bet']
        p1_enable_bet = players[room][player1_sid]['enable_bet']
        p2_enable_bet = players[room][player2_sid]['enable_bet']

        if p1_enable_bet != p2_enable_bet or (p1_enable_bet and p1_bet != p2_bet):
            emit('error', {'message': 'Ambos jugadores deben coincidir en apostar o no, y en el monto'}, room=room)
            del players[room][player2_sid]
            leave_room(room, player2_sid)
            return

        bet_amount = p1_bet if p1_enable_bet else 0
        if bet_amount > 0:
            p1_balance = load_wallet(sessions[player1_sid])
            p2_balance = load_wallet(sessions[player2_sid])
            save_wallet(sessions[player1_sid], p1_balance - bet_amount)
            save_wallet(sessions[player2_sid], p2_balance - bet_amount)
            emit('wallet_update', {'balance': load_wallet(sessions[player1_sid])}, to=player1_sid)
            emit('wallet_update', {'balance': load_wallet(sessions[player2_sid])}, to=player2_sid)
            print(f"Apuesta de ${bet_amount} deducida")

        emit('bet_accepted', {'bet': bet_amount}, room=room)
        time_per_player = timer_minutes * 60 if timer_minutes > 0 else None
        if time_per_player:
            games[room]['time_white'] = time_per_player
            games[room]['time_black'] = time_per_player
            games[room]['last_move_time'] = time.time()

        player_colors = {players[room][sid]['color']: players[room][sid]['chosen_color'] for sid in players[room]}
        socketio.emit('game_start', {
            'board': games[room]['board'],
            'turn': games[room]['turn'],
            'time_white': games[room]['time_white'],
            'time_black': games[room]['time_black'],
            'playerColors': player_colors
        }, room=room)
        print(f"Juego iniciado en {room} con turno inicial: {games[room]['turn']}, apuesta: {bet_amount} ARS")
    else:
        emit('waiting_opponent', {'message': 'Esperando a otro jugador...'}, to=sid)

@socketio.on('watch_game')
def on_watch_game(data):
    room = data['room']
    sid = request.sid
    username = sessions.get(sid)
    if not username:
        emit('error', {'message': 'Debes iniciar sesión'}, to=sid)
        return
    if room in games:
        if games[room]['is_public']:
            join_room(room)
            emit('game_start', games[room], to=sid)
        elif load_wallet(username) >= games[room]['view_cost']:
            current_balance = load_wallet(username)
            save_wallet(username, current_balance - games[room]['view_cost'])
            emit('wallet_update', {'balance': load_wallet(username)}, to=sid)
            join_room(room)
            emit('game_start', games[room], to=sid)
        else:
            emit('error', {'message': 'Fondos insuficientes para ver la partida'}, to=sid)

@socketio.on('play_against_bot')
def handle_play_against_bot(data):
    sid = request.sid
    fen = data.get('fen', chess.STARTING_FEN)  # Posición inicial por defecto
    board = chess.Board(fen)
    
    if not board.is_game_over():
        result = engine.play(board, chess.engine.Limit(time=0.1))  # 0.1 segundos de思考
        move = result.move
        board.push(move)
        emit('bot_move', {'move': move.uci(), 'fen': board.fen()}, room=sid)
    
    if board.is_game_over():
        emit('game_over', {'result': board.result()}, room=sid)

@socketio.on('move')
def on_move(data):
    room = data['room']
    sid = request.sid
    start_row = data['start_row']
    start_col = data['start_col']
    end_row = data['end_row']
    end_col = data['end_col']
    print(f"Movimiento recibido en {room} por {sid}: {start_row},{start_col} a {end_row},{end_col}")

    if room in games and room in players and sid in players[room]:
        board = games[room]['board']
        turn = games[room]['turn']
        piece = board[start_row][start_col]
        player_color = players[room][sid]['color']
        print(f"Turno actual: {turn}, Color del jugador: {player_color}")

        if turn != player_color:
            print(f"Movimiento inválido: No es el turno de {player_color}")
            return

        if piece != '.' and ((turn == 'white' and is_white(piece)) or (turn == 'black' and is_black(piece))):
            if is_valid_move(piece, start_row, start_col, end_row, end_col, board):
                temp_board = [row[:] for row in board]
                temp_board[end_row][end_col] = piece
                temp_board[start_row][start_col] = '.'
                if not is_in_check(temp_board, turn):
                    board[end_row][end_col] = piece
                    board[start_row][start_col] = '.'
                    games[room]['turn'] = 'black' if turn == 'white' else 'white'
                    update_timer(room)
                    socketio.emit('update_board', {'board': board, 'turn': games[room]['turn']}, room=room)
                    if is_in_check(board, games[room]['turn']):
                        socketio.emit('check', {'message': '¡Jaque!'}, room=room)
                        if is_checkmate(board, games[room]['turn']):
                            winner_sid = sid if turn == player_color else list(players[room].keys())[0] if turn == 'black' else list(players[room].keys())[1]
                            socketio.emit('game_over', {'message': '¡Jaque mate! Gana ' + ('blancas' if turn == 'black' else 'negras'), 'winner_sid': winner_sid}, room=room)
                            if room in players:
                                del players[room]
                            if room in games:
                                del games[room]
                else:
                    print(f"Movimiento inválido: Deja al rey en jaque")
            else:
                print(f"Movimiento inválido: Regla de pieza no cumplida")
        else:
            print(f"Movimiento inválido: Pieza incorrecta para el turno {turn}")

@socketio.on('resign')
def on_resign(data):
    room = data['room']
    sid = request.sid
    if room in players and len(players[room]) == 2:
        winner_sid = [s for s in players[room] if s != sid][0]
        bet_amount = players[room][sid]['bet'] if players[room][sid]['enable_bet'] else 0
        if bet_amount > 0:
            winner_prize = bet_amount * 2 * 0.9
            winner_balance = load_wallet(sessions[winner_sid])
            save_wallet(sessions[winner_sid], winner_balance + winner_prize)
            emit('wallet_update', {'balance': load_wallet(sessions[winner_sid])}, to=winner_sid)
            emit('wallet_update', {'balance': load_wallet(sessions[sid])}, to=sid)
            emit('resigned', {'message': f'Oponente abandonó. Ganaste ${winner_prize} ARS.', 'new_balance': load_wallet(sessions[winner_sid])}, to=winner_sid)
            emit('resigned', {'message': 'Abandonaste la partida.', 'new_balance': load_wallet(sessions[sid])}, to=sid)
        else:
            emit('resigned', {'message': 'Oponente abandonó. ¡Ganaste!'}, to=winner_sid)
            emit('resigned', {'message': 'Abandonaste la partida.'}, to=sid)
        if room in players:
            del players[room]
        if room in games:
            del games[room]

# Eventos Socket.IO - Lista de Espera y Chat Privado
@socketio.on('join_waitlist')
def on_join_waitlist(data):
    sid = request.sid
    username = sessions.get(sid)
    chosen_color = data.get('color', '#FFFFFF')
    avatar = data.get('avatar', '/static/default-avatar.png')
    print(f"Recibido join_waitlist: sid={sid}, username={username}, color={chosen_color}, avatar={avatar}")
    if username and sid not in available_players:
        available_players[sid] = {'username': username, 'chosen_color': chosen_color, 'avatar': avatar}
        print(f"{username} ({sid}) se unió a la lista de espera con avatar {avatar}")
        players_list = [{'sid': s, 'username': info['username'], 'chosen_color': info['chosen_color'], 'avatar': info['avatar']} 
                        for s, info in available_players.items()]
        socketio.emit('waitlist_update', {'players': players_list})
    else:
        print(f"Fallo al unir a {sid} a la lista de espera: username={username}, ya en lista={sid in available_players}")

@socketio.on('select_opponent')
def on_select_opponent(data):
    opponent_sid = data.get('opponent_sid')
    player_sid = request.sid
    username = sessions.get(player_sid)
    
    print(f"Recibido select_opponent: player_sid={player_sid}, username={username}, opponent_sid={opponent_sid}")
    
    if not opponent_sid or opponent_sid not in available_players:
        emit('error', {'message': 'El oponente seleccionado no está disponible.'})
        return
    
    if player_sid not in available_players:
        emit('error', {'message': 'No estás en la lista de espera.'})
        return

    player_data = available_players[player_sid]
    opponent_data = available_players[opponent_sid]
    
    room = f"private_{player_sid}_{opponent_sid}"
    print(f"Creando sala privada: {room}")
    
    players[room] = {
        player_sid: {'color': 'white', 'chosen_color': player_data['chosen_color'], 'avatar': player_data['avatar'], 'bet': 0, 'enable_bet': False},
        opponent_sid: {'color': 'black', 'chosen_color': opponent_data['chosen_color'], 'avatar': opponent_data['avatar'], 'bet': 0, 'enable_bet': False}
    }
    
    del available_players[player_sid]
    del available_players[opponent_sid]
    
    emit('private_chat_start', {'room': room, 'opponent': opponent_data['username'], 'players': players[room]}, to=player_sid)
    emit('private_chat_start', {'room': room, 'opponent': username, 'players': players[room]}, to=opponent_sid)
    
    players_list = [{'sid': s, 'username': info['username'], 'chosen_color': info['chosen_color'], 'avatar': info['avatar']} 
                    for s, info in available_players.items()]
    socketio.emit('waitlist_update', {'players': players_list})

@socketio.on('leave_waitlist')
def on_leave_waitlist():
    sid = request.sid
    if sid in available_players:
        username = available_players[sid]['username']
        del available_players[sid]
        print(f"{username} ({sid}) salió de la lista de espera")
        players_list = [{'sid': s, 'username': info['username'], 'chosen_color': info['chosen_color'], 'avatar': info['avatar']} 
                        for s, info in available_players.items()]
        socketio.emit('waitlist_update', {'players': players_list})

@socketio.on('leave_private_chat')
def on_leave_private_chat(data):
    sid = request.sid
    room = data['room']
    if room in players and sid in players[room]:
        del players[room][sid]
        if not players[room]:
            del players[room]
            if room in games:
                del games[room]
        else:
            socketio.emit('player_left', {'message': 'Opponent disconnected'}, room=room)
        leave_room(room)
        print(f"{sid} salió del chat privado en {room}")

@socketio.on('private_message')
def on_private_message(data):
    room = data['room']
    sid = request.sid
    message = data['message']
    username = sessions.get(sid)
    if room in players and sid in players[room]:
        color = players[room][sid]['chosen_color']
        socketio.emit('private_message', {'username': username, 'color': color, 'message': message}, room=room)

@socketio.on('accept_conditions')
def on_accept_conditions(data):
    room = data['room']
    sid = request.sid
    bet = int(data.get('bet', 0))
    enable_bet = data.get('enableBet', False)
    if room in players and sid in players[room]:
        players[room][sid]['bet'] = bet
        players[room][sid]['enable_bet'] = enable_bet
        opponent_sid = [s for s in players[room] if s != sid][0]
        if (players[room][opponent_sid]['bet'] == bet and 
            players[room][opponent_sid]['enable_bet'] == enable_bet):
            bet_amount = bet if enable_bet else 0
            if bet_amount > 0:
                sid_balance = load_wallet(sessions[sid])
                opponent_balance = load_wallet(sessions[opponent_sid])
                if sid_balance < bet_amount or opponent_balance < bet_amount:
                    emit('error', {'message': 'Fondos insuficientes'}, room=room)
                    return
                save_wallet(sessions[sid], sid_balance - bet_amount)
                save_wallet(sessions[opponent_sid], opponent_balance - bet_amount)
                emit('wallet_update', {'balance': load_wallet(sessions[sid])}, to=sid)
                emit('wallet_update', {'balance': load_wallet(sessions[opponent_sid])}, to=opponent_sid)
            emit('bet_accepted', {'bet': bet_amount}, room=room)
            board, turn = reset_board(room)
            games[room] = {
                'board': board,
                'turn': turn,
                'time_white': None,
                'time_black': None,
                'last_move_time': None
            }
            player_colors = {players[room][sid]['color']: players[room][sid]['chosen_color'] for sid in players[room]}
            socketio.emit('game_start', {
                'board': board,
                'turn': turn,
                'time_white': None,
                'time_black': None,
                'playerColors': player_colors
            }, room=room)
        else:
            emit('waiting_opponent', {'message': 'Esperando aceptación del oponente'}, to=sid)

# Eventos Socket.IO - Chat y Multimedia
@socketio.on('chat_message')
def on_chat_message(data):
    room = data['room']
    sid = request.sid
    message = data['message']
    color = players[room][sid]['color']
    socketio.emit('new_message', {'color': color, 'message': message}, room=room)

@socketio.on('audio_message')
def on_audio_message(data):
    room = data['room']
    sid = request.sid
    if room in players and sid in players[room]:
        audio_data = data['audio']
        color = players[room][sid]['color']
        socketio.emit('audio_message', {'color': color, 'audio': audio_data}, room=room)

@socketio.on('video_signal')
def on_video_signal(data):
    room = data['room']
    sid = request.sid
    signal = data['signal']
    for player_sid in players[room]:
        if player_sid != sid:
            emit('video_signal', {'signal': signal}, to=player_sid)

# Eliminamos play_with_bot y usamos solo play_against_bot para consistencia con el frontend
@socketio.on('play_with_bot')  # Redirigimos este evento al correcto
def on_play_with_bot(data):
    handle_play_against_bot(data)

@socketio.on('move_with_bot')  # No necesario con el frontend actual, pero lo dejamos por si lo usás
def on_move_with_bot(data):
    room = data['room']
    sid = request.sid
    if room.startswith('bot_') and room in games and sid in players[room]:
        on_move(data)
        if room in games and games[room]['turn'] == 'black':
            board = games[room]['board']
            chess_board = chess.Board(''.join(''.join(row) for row in board))
            move = list(chess_board.legal_moves)[0]
            chess_board.push(move)
            new_board = [['.' for _ in range(8)] for _ in range(8)]
            for square in chess.SQUARES:
                piece = chess_board.piece_at(square)
                if piece:
                    new_board[7 - chess.square_rank(square)][chess.square_file(square)] = str(piece)
            games[room]['board'] = new_board
            games[room]['turn'] = 'white'
            socketio.emit('update_board', {'board': new_board, 'turn': 'white'}, room=room)

@socketio.on('global_message')
def on_global_message(data):
    sid = request.sid
    username = sessions.get(sid)
    if username:
        emit('global_message', {'username': username, 'message': data['message']}, broadcast=True)

@socketio.on('video_stop')
def on_video_stop(data):
    room = data['room']
    sid = request.sid
    if room in players and sid in players[room]:
        for player_sid in players[room]:
            if player_sid != sid:
                emit('video_stop', to=player_sid)

# Eventos Socket.IO - Guardado de Partidas
@socketio.on('save_game')
def on_save_game(data):
    room = data['room']
    sid = request.sid
    username = sessions.get(sid)
    if not username:
        emit('error', {'message': 'No estás autenticado'}, to=sid)
        return
    game_name = data['game_name']
    board_json = json.dumps(data['board'])
    turn = data['turn']
    conn = sqlite3.connect(DATABASE_PATH)
    c = conn.cursor()
    c.execute('INSERT INTO saved_games (username, room, game_name, board, turn) VALUES (?, ?, ?, ?, ?)', 
              (username, room, game_name, board_json, turn))
    conn.commit()
    conn.close()
    socketio.emit('game_saved', {'message': f'Partida "{game_name}" guardada exitosamente'}, room=room)

@socketio.on('get_saved_games')
def on_get_saved_games(data):
    username = data['username']
    sid = request.sid
    conn = sqlite3.connect(DATABASE_PATH)
    c = conn.cursor()
    c.execute('SELECT game_name, room FROM saved_games WHERE username = ?', (username,))
    games_list = [{'game_name': row[0], 'room': row[1]} for row in c.fetchall()]
    conn.close()
    socketio.emit('saved_games_list', {'games': games_list}, to=sid)

@socketio.on('load_game')
def on_load_game(data):
    username = data['username']
    game_name = data['game_name']
    sid = request.sid
    conn = sqlite3.connect(DATABASE_PATH)
    c = conn.cursor()
    c.execute('SELECT board, turn, room FROM saved_games WHERE username = ? AND game_name = ?', (username, game_name))
    result = c.fetchone()
    conn.close()
    if result:
        board = json.loads(result[0])
        turn = result[1]
        room = result[2]
        join_room(room)
        if room not in players:
            players[room] = {}
        if len(players[room]) >= 2:
            emit('error', {'message': 'La sala está llena'}, to=sid)
            leave_room(room)
            return
        color = 'white' if len(players[room]) == 0 else 'black'
        players[room][sid] = {'color': color, 'chosen_color': '#FFFFFF', 'bet': 0, 'enable_bet': False}
        emit('color_assigned', {'color': color, 'chosenColor': '#FFFFFF'}, to=sid)
        games[room] = {'board': board, 'turn': turn, 'time_white': None, 'time_black': None, 'last_move_time': None}
        emit('game_loaded', {'board': board, 'turn': turn, 'game_name': game_name, 'room': room}, to=sid)
        if len(players[room]) == 2:
            player_colors = {players[room][sid]['color']: players[room][sid]['chosen_color'] for sid in players[room]}
            socketio.emit('game_start', {
                'board': board,
                'turn': turn,
                'time_white': None,
                'time_black': None,
                'playerColors': player_colors
            }, room=room)

# Eventos Socket.IO - Billetera
@socketio.on('deposit_request')
def on_deposit_request(data):
    sid = request.sid
    amount = data['amount']
    username = sessions.get(sid)
    if not username:
        emit('error', {'message': 'Debes iniciar sesión primero'}, to=sid)
        return
    preference = {
        "items": [{"title": "Recarga PeonKing", "quantity": 1, "currency_id": "ARS", "unit_price": float(amount)}],
        "payer": {"email": "rodrigo.n.arena@hotmail.com"},
        "external_reference": username,
        "back_urls": {
            "success": "https://peonkingame.onrender.com/success",
            "failure": "https://peonkingame.onrender.com/failure",
            "pending": "https://peonkingame.onrender.com/pending"
        },
        "auto_return": "approved"
    }
    preference_result = sdk.preference().create(preference)
    emit('deposit_url', {'preference_id': preference_result['response']['id']}, to=sid)

@socketio.on('check_deposit')
def on_check_deposit(data):
    sid = request.sid
    username = sessions.get(sid)
    if not username:
        emit('error', {'message': 'Sesión inválida'}, to=sid)
        return
    payment = sdk.payment().search({'external_reference': username, 'status': 'approved'})
    if payment['results']:
        amount = payment['results'][0]['transaction_amount']
        current_balance = load_wallet(username)
        new_balance = current_balance + amount
        save_wallet(username, new_balance)
        emit('wallet_update', {'balance': new_balance}, to=sid)

@socketio.on('withdraw_request')
def on_withdraw_request(data):
    sid = request.sid
    amount = data['amount']
    username = sessions.get(sid)
    current_balance = load_wallet(username)
    if current_balance >= amount:
        save_wallet(username, current_balance - amount)
        emit('withdraw_success', {'amount': amount}, to=sid)
        emit('wallet_update', {'balance': load_wallet(username)}, to=sid)

# Inicio del Servidor
if __name__ == '__main__':
    players.clear()
    games.clear()
    port = int(os.getenv("PORT", 10000))  # Cambiado a 10000 para coincidir con Render
    socketio.run(app, host='0.0.0.0', port=port, debug=not os.getenv('RENDER'))
