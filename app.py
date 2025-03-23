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

# Configuración Inicial
app = Flask(__name__)
app.secret_key = os.getenv("Ma730yIan")  # Cambia esto por una clave secreta fuerte
socketio = SocketIO(app, cors_allowed_origins="*")

DATABASE_PATH = '/opt/render/project/src/users.db' if os.getenv('RENDER') else 'users.db'
sdk = mercadopago.SDK("APP_USR-5091391065626033-031704-d3f30ae7f58f6a82763a55123c451a14-2326694132") # Access Token

# Variables Globales
sessions = {}  # Almacena sid -> username
players = {}  # {room: {sid: {'color': str, 'chosen_color': str, 'bet': int, 'enable_bet': bool}}}
games = {}  # {room: {'board': list, 'turn': str, 'time_white': float, 'time_black': float, 'last_move_time': float}}
wallets = {}  # {sid: float}
online_players = {}  # Lista de jugadores en línea
available_players = {}  # {sid: {'username': str, 'chosen_color': str}}

initial_board = [
    ['r', 'n', 'b', 'q', 'k', 'b', 'n', 'r'],
    ['p', 'p', 'p', 'p', 'p', 'p', 'p', 'p'],
    ['.', '.', '.', '.', '.', '.', '.', '.'],
    ['.', '.', '.', '.', '.', '.', '.', '.'],
    ['.', '.', '.', '.', '.', '.', '.', '.'],
    ['.', '.', '.', '.', '.', '.', '.', '.'],
    ['P', 'P', 'P', 'P', 'P', 'P', 'P', 'P'],
    ['R', 'N', 'B', 'Q', 'K', 'B', 'N', 'R']
]

# Funciones de Lógica del Ajedrez
def reset_board(room):
    games[room] = {
        'board': [row[:] for row in initial_board],
        'turn': 'white',
        'time_white': None,
        'time_black': None,
        'last_move_time': None
    }
    return games[room]['board'], games[room]['turn']

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
            if piece != '.' and (color == 'white' and is_black(piece)) or (color == 'black' and is_white(piece)):
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

def load_wallets():
    try:
        with open('wallets.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_wallets(wallets):
    with open('wallets.json', 'w') as f:
        json.dump(wallets, f)

wallets = load_wallets()

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
            reset_board(room)
            if room in players:
                del players[room]
        elif games[room]['time_black'] <= 0:
            socketio.emit('game_over', {'message': '¡Tiempo agotado! Gana blancas'}, room=room)
            reset_board(room)
            if room in players:
                del players[room]
                
def init_db():
    conn = sqlite3.connect(DATABASE_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password BLOB, avatar TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS saved_games (username TEXT, room TEXT, game_name TEXT, board TEXT, turn TEXT)''')
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
    if wallets.get(request.sid, 0) >= amount:
        wallets[request.sid] -= amount
        emit('withdraw_success', {'amount': amount}, to=request.sid)
        emit('wallet_update', {'balance': wallets[request.sid]}, to=request.sid)
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

@app.route('/login', methods=['POST'])
def login():
    username = request.form.get('username')
    if username:
        sid = request.sid if hasattr(request, 'sid') else None  # Solo para SocketIO, ajustar si usas Flask puro
        if sid:
            sessions[sid] = username
        return {'success': True}
        return {'success': False, 'error': 'Username requerido'}
    password = request.form.get('password')
    conn = sqlite3.connect(DATABASE_PATH)
    c = conn.cursor()
    c.execute('SELECT password FROM users WHERE username = ?', (username,))
    result = c.fetchone()
    conn.close()
    if result and bcrypt.checkpw(password.encode('utf-8'), result[0]):
        session['username'] = username
        return jsonify({'success': True})
    return jsonify({'error': 'Usuario o contraseña incorrectos'}), 401

@app.route('/register', methods=['POST'])
def register():
    username = request.form.get('username')
    password = request.form.get('password')
    avatar = request.files.get('avatar')  # Obtener el archivo subido
    if not username or not password:
        return jsonify({'error': 'Usuario y contraseña requeridos'}), 400
    hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
    avatar_path = 'default-avatar.png'
    if avatar:
        # Crear el directorio static/avatars si no existe
        avatar_dir = os.path.join(app.root_path, 'static', 'avatars')
        if not os.path.exists(avatar_dir):
            os.makedirs(avatar_dir)
        # Guardar el archivo con un nombre único
        avatar_filename = f"{username}_{avatar.filename}"
        avatar_path = os.path.join('static', 'avatars', avatar_filename)
        avatar.save(avatar_path)  # Guardar la imagen en el servidor
        print(f"Avatar guardado en: {avatar_path}")
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        c = conn.cursor()
        c.execute('INSERT INTO users (username, password, avatar) VALUES (?, ?, ?)', (username, hashed_password, avatar_path))
        conn.commit()
        conn.close()
        session['username'] = username
        return jsonify({'success': True})
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
    return jsonify({'avatar': result[0] if result else 'default-avatar.png'})

# Eventos Socket.IO - Conexión y Desconexión
@socketio.on('connect')
def on_connect():
    sid = request.sid
    print(f"Cliente conectado: {sid}")
    if sid not in wallets:
        wallets[sid] = 0
    if 'username' in session:
        online_players[sid] = {'username': session['username'], 'avatar': session.get('avatar', 'default-avatar.png')}
        emit('online_players_update', list(online_players.values()), broadcast=True)  # Inicializar billetera solo cuando un cliente se conecta

@socketio.on('disconnect')
def on_disconnect():
    sid = request.sid
    # Limpieza de lista de espera
    if sid in available_players:
        del available_players[sid]
        socketio.emit('waitlist_update', {'players': [{'sid': s, 'username': info['username'], 'chosen_color': info['chosen_color']} for s, info in available_players.items()]}, broadcast=True)
    # Limpieza de salas de juego
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
    # Limpieza de jugadores en línea
    if sid in online_players:
        del online_players[sid]
        emit('online_players_update', list(online_players.values()), broadcast=True)
    print(f"Cliente desconectado: {sid}")
    
# Evento para unir al usuario a su propia sala (opcional, para emitir eventos por username)
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
    join_room(room)

    print(f"Jugador {sid} intentando unirse a {room}. Apostar: {enable_bet}, Monto: {bet}")
    if sid not in wallets:
        wallets[sid] = 0
    if enable_bet and wallets[sid] < bet:
        emit('error', {'message': 'Fondos insuficientes para la apuesta'}, to=sid)
        leave_room(room)
        return

    if room not in players:
        players[room] = {}
    if len(players[room]) >= 2:
        emit('error', {'message': 'La sala está llena'}, to=sid)
        leave_room(room)
        return

    players[room][sid] = {'color': 'white' if len(players[room]) == 0 else 'black', 'chosen_color': chosen_color, 'bet': bet, 'enable_bet': enable_bet}
    emit('color_assigned', {'color': players[room][sid]['color'], 'chosenColor': chosen_color}, to=sid)
    print(f"Jugador {sid} asignado a {room} como {players[room][sid]['color']}")

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
            wallets[player1_sid] -= bet_amount
            wallets[player2_sid] -= bet_amount
            emit('wallet_update', {'balance': wallets[player1_sid]}, to=player1_sid)
            emit('wallet_update', {'balance': wallets[player2_sid]}, to=player2_sid)
            print(f"Apuesta de ${bet_amount} deducida")

        emit('bet_accepted', {'bet': bet_amount}, room=room)
        board, turn = reset_board(room)
        time_per_player = timer_minutes * 60 if timer_minutes > 0 else None
        if time_per_player:
            games[room]['time_white'] = time_per_player
            games[room]['time_black'] = time_per_player
            games[room]['last_move_time'] = time.time()
        player_colors = {players[room][sid]['color']: players[room][sid]['chosen_color'] for sid in players[room]}
        socketio.emit('game_start', {
            'board': board,
            'turn': turn,
            'time_white': games[room]['time_white'] if time_per_player else None,
            'time_black': games[room]['time_black'] if time_per_player else None,
            'playerColors': player_colors
        }, room=room)
        print(f"Juego iniciado en {room} con turno inicial: {turn}, apuesta: {bet_amount} ARS")

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
            wallets[winner_sid] = wallets.get(winner_sid, 0) + winner_prize
            emit('wallet_update', {'balance': wallets[winner_sid]}, to=winner_sid)
            emit('wallet_update', {'balance': wallets[sid]}, to=sid)
            emit('resigned', {'message': f'Oponente abandonó. Ganaste ${winner_prize} ARS.', 'new_balance': wallets[winner_sid]}, to=winner_sid)
            emit('resigned', {'message': 'Abandonaste la partida.', 'new_balance': wallets[sid]}, to=sid)
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
    username = session.get('username')
    chosen_color = data.get('color', '#FFFFFF')
    avatar = data.get('avatar', '/static/default-avatar.png')
    print(f"Recibido join_waitlist: sid={sid}, username={username}, color={chosen_color}, avatar={avatar}")
    if username and sid not in available_players:
        available_players[sid] = {'username': username, 'chosen_color': chosen_color, 'avatar': avatar}
        print(f"{username} ({sid}) se unió a la lista de espera con avatar {avatar}")
        # Emitir la actualización a todos los clientes
        players_list = [{'sid': s, 'username': info['username'], 'chosen_color': info['chosen_color'], 'avatar': info['avatar']} 
                        for s, info in available_players.items()]
        print(f"Emitting waitlist_update con {len(players_list)} jugadores: {players_list}")
        socketio.emit('waitlist_update', {'players': players_list}, broadcast=True)
    else:
        print(f"Fallo al unir a {sid} a la lista de espera: username={username}, ya en lista={sid in available_players}")
        
@socketio.on('select_opponent')
def on_select_opponent(data):
    opponent_sid = data.get('opponent_sid')
    player_sid = request.sid
    username = session.get('username')
    
    print(f"Recibido select_opponent: player_sid={player_sid}, username={username}, opponent_sid={opponent_sid}")
    
    if not opponent_sid or opponent_sid not in available_players:
        print(f"Error: opponent_sid {opponent_sid} no encontrado en available_players: {available_players}")
        emit('error', {'message': 'El oponente seleccionado no está disponible.'})
        return
    
    if player_sid not in available_players:
        print(f"Error: player_sid {player_sid} no está en available_players")
        emit('error', {'message': 'No estás en la lista de espera.'})
        return

    # Obtener datos de ambos jugadores
    player_data = available_players[player_sid]
    opponent_data = available_players[opponent_sid]
    
    # Crear una sala única para el chat privado
    room = f"private_{player_sid}_{opponent_sid}"
    print(f"Creando sala privada: {room}")
    
    # Asignar colores (por ejemplo, el que inicia es blanco)
    players = {
        player_sid: {'color': 'white', 'chosen_color': player_data['chosen_color'], 'avatar': player_data['avatar'], 'bet': 0, 'enable_bet': False},
        opponent_sid: {'color': 'black', 'chosen_color': opponent_data['chosen_color'], 'avatar': opponent_data['avatar'], 'bet': 0, 'enable_bet': False}
    }
    
    # Sacar a ambos de la lista de espera
    del available_players[player_sid]
    del available_players[opponent_sid]
    
    # Notificar a ambos jugadores del inicio del chat privado
    emit('private_chat_start', {'room': room, 'opponent': opponent_data['username'], 'players': players}, to=player_sid)
    emit('private_chat_start', {'room': room, 'opponent': username, 'players': players}, to=opponent_sid)
    
    # Actualizar la lista de espera para todos
    players_list = [{'sid': s, 'username': info['username'], 'chosen_color': info['chosen_color'], 'avatar': info['avatar']} 
                    for s, info in available_players.items()]
    print(f"Emitting waitlist_update tras selección: {players_list}")
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
        print(f"Emitting waitlist_update tras salir: {players_list}")
        socketio.emit('waitlist_update', {'players': players_list})  # Sin broadcast=True
    else:
        print(f"Intento de salir fallido: {sid} no encontrado en available_players")

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
    username = session.get('username')
    print(f"Mensaje privado en {room} de {username}: {message}")
    if room in players and sid in players[room]:
        color = players[room][sid]['chosen_color']  # Usar chosen_color
        socketio.emit('private_message', {'username': username, 'color': color, 'message': message}, room=room)
    else:
        emit('error', {'message': 'No estás en esa sala'}, to=sid)

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
                if wallets.get(sid, 0) < bet_amount or wallets.get(opponent_sid, 0) < bet_amount:
                    emit('error', {'message': 'Fondos insuficientes'}, room=room)
                    return
                wallets[sid] -= bet_amount
                wallets[opponent_sid] -= bet_amount
                emit('wallet_update', {'balance': wallets[sid]}, to=sid)
                emit('wallet_update', {'balance': wallets[opponent_sid]}, to=opponent_sid)
            emit('bet_accepted', {'bet': bet_amount}, room=room)
            board, turn = reset_board(room)
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
    print(f"Mensaje en {room} de {sid} ({color}): {message}")
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
    print(f"Señal WebRTC recibida de {sid} en {room}")
    for player_sid in players[room]:
        if player_sid != sid:
            print(f"Enviando señal a {player_sid}")
            emit('video_signal', {'signal': signal}, to=player_sid)
            
@socketio.on('play_with_bot')
def on_play_with_bot(data):
    sid = request.sid
    room = f"bot_{sid}"
    players[room] = {request.sid: {'color': 'white', 'chosen_color': '#000000'}}
    board, turn = reset_board(room)
    emit('game_start', {'board': board, 'turn': 'white', 'time_white': 600, 'time_black': 600, 'playerColors': {'white': '#000000', 'black': '#FF0000'}}, room=room)
    print(f"Partida contra bot iniciada en {room} para {sid}")
    # Bot juega como negro (responde después del primer movimiento del jugador)
    
# Bot responde después de un movimiento del jugador
@socketio.on('move')
def on_move_with_bot(data):
    room = data['room']
    sid = request.sid
    if room.startswith('bot_') and room in games and sid in players[room]:
        on_move(data)  # Procesa el movimiento del jugador
        if room in games and games[room]['turn'] == 'black':  # Turno del bot
            board = games[room]['board']
            chess_board = chess.Board(''.join(''.join(row) for row in board))
            move = list(chess_board.legal_moves)[0]  # Elige el primer movimiento legal (simple bot)
            chess_board.push(move)
            new_board = [['.' for _ in range(8)] for _ in range(8)]
            for square in chess.SQUARES:
                piece = chess_board.piece_at(square)
                if piece:
                    new_board[7 - chess.square_rank(square)][chess.square_file(square)] = str(piece)
            games[room]['board'] = new_board
            games[room]['turn'] = 'white'
            socketio.emit('update_board', {'board': new_board, 'turn': 'white'}, room=room)
            print(f"Bot movió en {room}: {move.uci()}")
    
@socketio.on('global_message')
def on_global_message(data):
    emit('global_message', {'username': session['username'], 'message': data['message']}, broadcast=True)

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
    if room in players and sid in players[room]:
        username = session.get('username')
        if not username:
            emit('error', {'message': 'No estás autenticado'}, to=sid)
            return
        game_name = data['game_name']
        board_json = json.dumps(data['board'])
        turn = data['turn']
        try:
            conn = sqlite3.connect(DATABASE_PATH)
            c = conn.cursor()
            c.execute('''INSERT INTO saved_games (username, room, game_name, board, turn)
                         VALUES (?, ?, ?, ?, ?)''', (username, room, game_name, board_json, turn))
            conn.commit()
            conn.close()
            socketio.emit('game_saved', {'message': f'Partida "{game_name}" guardada exitosamente'}, room=room)
        except sqlite3.IntegrityError:
            emit('error', {'message': f'Ya existe una partida guardada con el nombre "{game_name}"'}, to=sid)
        except Exception as e:
            emit('error', {'message': 'Error al guardar la partida'}, to=sid)
            print(f"Error al guardar partida: {e}")

@socketio.on('get_saved_games')
def on_get_saved_games(data):
    username = data['username']
    sid = request.sid
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        c = conn.cursor()
        c.execute('SELECT game_name, room FROM saved_games WHERE username = ?', (username,))
        games_list = [{'game_name': row[0], 'room': row[1]} for row in c.fetchall()]
        conn.close()
        socketio.emit('saved_games_list', {'games': games_list}, to=sid)
    except Exception as e:
        emit('error', {'message': 'Error al obtener las partidas guardadas'}, to=sid)
        print(f"Error al obtener partidas: {e}")

# Evento para obtener el saldo actual
@socketio.on('get_wallet_balance')
def on_get_wallet_balance(data):
    username = data['username']
    balance = wallets.get(username, 0)
    emit('wallet_balance', {'balance': balance}, to=request.sid)
    
@socketio.on('load_game')
def on_load_game(data):
    username = data['username']
    game_name = data['game_name']
    sid = request.sid
    try:
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
        else:
            emit('error', {'message': 'Partida no encontrada'}, to=sid)
    except Exception as e:
        emit('error', {'message': 'Error al cargar la partida'}, to=sid)
        print(f"Error al cargar partida: {e}")

# Eventos Socket.IO - Billetera
@socketio.on('deposit_request')
def on_deposit_request(data):
    sid = request.sid
    amount = data['amount']
    username = sessions.get(sid)  # Obtener username de la sesión
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
    try:
        preference_result = sdk.preference().create(preference)
        if 'response' in preference_result and 'id' in preference_result['response']:
            preference_id = preference_result['response']['id']
            emit('deposit_url', {'preference_id': preference_id}, to=sid)
        else:
            emit('error', {'message': 'Respuesta inválida de MercadoPago'}, to=sid)
    except Exception as e:
        print(f"Excepción al crear preferencia: {str(e)}")
        emit('error', {'message': 'Error al procesar la recarga'}, to=sid)

@socketio.on('check_deposit')
def on_check_deposit(data):
    sid = request.sid
    username = sessions.get(sid)  # Obtener username de la sesión
    if not username:
        emit('error', {'message': 'Sesión inválida'}, to=sid)
        return
    payment = sdk.payment().search({'external_reference': username, 'status': 'approved'})    
    if payment['results']:
        amount = payment['results'][0]['transaction_amount']
        wallets[username] = wallets.get(sid, 0) + amount
        save_wallets(wallets)  # Guardar después de actualizar
        emit('wallet_update', {'balance': wallets[username]}, to=sid)
        print(f"Depósito de {amount} ARS aprobado para {username}. Nuevo saldo: {wallets[username]}")
    else:
        print(f"No se encontraron pagos aprobados para {username}")

@socketio.on('withdraw_request')
def on_withdraw_request(data):
    sid = request.sid
    amount = data['amount']
    if wallets.get(sid, 0) >= amount:
        wallets[sid] -= amount
        emit('withdraw_success', {'amount': amount}, to=sid)
        emit('wallet_update', {'balance': wallets[sid]}, to=sid)
    else:
        emit('error', {'message': 'Fondos insuficientes'}, to=sid)

# Inicio del Servidor
if __name__ == '__main__':
    print("Limpiando players y games al inicio...")
    players.clear()
    games.clear()
    conn = sqlite3.connect(DATABASE_PATH)
    c = conn.cursor()
    
    # Crear tabla users si no existe
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        username TEXT UNIQUE,
        password TEXT,
        avatar TEXT DEFAULT 'default-avatar.png'
    )''')
    
    # Crear tabla saved_games si no existe
    c.execute('''CREATE TABLE IF NOT EXISTS saved_games (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        room TEXT,
        game_name TEXT,
        board TEXT,
        turn TEXT,
        UNIQUE(username, game_name)
    )''')
    
    # Verificar si la columna avatar ya existe antes de intentar agregarla
    c.execute("PRAGMA table_info(users)")
    columns = [col[1] for col in c.fetchall()]  # Lista de nombres de columnas
    if 'avatar' not in columns:
        c.execute("ALTER TABLE users ADD COLUMN avatar TEXT DEFAULT 'default-avatar.png'")
        print("Columna 'avatar' añadida a la tabla 'users'.")
    else:
        print("La columna 'avatar' ya existe en la tabla 'users'.")
    
    conn.commit()
    conn.close()
    
    # Usar puerto dinámico para Render, con debug solo en local
    port = int(os.getenv("PORT", 5000))
    debug = os.getenv('RENDER') is None  # Debug solo en local, no en Render
    socketio.run(app, host='0.0.0.0', port=port, debug=debug)
