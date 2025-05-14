import os
import eventlet
eventlet.monkey_patch()
from flask import Flask, render_template, jsonify, request, session
from flask_socketio import SocketIO, emit, join_room, leave_room
import sqlite3
import bcrypt
import json
import time
import chess
import chess.engine
import uuid

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'Ma730yIan')
socketio = SocketIO(app, cors_allowed_origins="*")
DATABASE_PATH = '/opt/render/project/src/users.db' if os.getenv('RENDER') else 'users.db'
STOCKFISH_PATH = os.path.join(os.path.dirname(__file__), 'src', 'stockfish') if os.getenv('RENDER') else 'src/stockfish'

# Verificar si Stockfish existe
if not os.path.exists(STOCKFISH_PATH):
    print(f"Error: No se encontró Stockfish en {STOCKFISH_PATH}")

sessions = {}
players = {}
games = {}
online_players = {}
available_players = {}

def board_to_fen(board, turn):
    """Convertir el tablero interno a notación FEN."""
    fen = ''
    for row in board:
        empty = 0
        for square in row:
            if square == '.':
                empty += 1
            else:
                if empty > 0:
                    fen += str(empty)
                    empty = 0
                fen += square
        if empty > 0:
            fen += str(empty)
        fen += '/'
    fen = fen[:-1]
    fen += f" {'w' if turn == 'white' else 'b'} - - 0 1"
    return fen

def fen_to_board(fen):
    """Convertir notación FEN a tablero interno."""
    board = []
    fen_parts = fen.split(' ')
    rows = fen_parts[0].split('/')
    for row in rows:
        board_row = []
        for char in row:
            if char.isdigit():
                board_row.extend(['.'] * int(char))
            else:
                board_row.append(char)
        board.append(board_row)
    turn = 'white' if fen_parts[1] == 'w' else 'black'
    return board, turn

def reset_board():
    """Inicializar tablero de ajedrez."""
    return chess.Board()

def init_db():
    conn = sqlite3.connect(DATABASE_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password BLOB, avatar TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS saved_games (username TEXT, room TEXT, game_name TEXT, fen TEXT, turn TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS wallets (username TEXT PRIMARY KEY, neig REAL DEFAULT 10000, elo INTEGER DEFAULT 0, level INTEGER DEFAULT 0)''')
    conn.commit()
    conn.close()

init_db()

def load_user_data(username):
    conn = sqlite3.connect(DATABASE_PATH)
    c = conn.cursor()
    c.execute('SELECT neig, elo, level FROM wallets WHERE username = ?', (username,))
    result = c.fetchone()
    conn.close()
    return {'neig': result[0], 'elo': result[1], 'level': result[2]} if result else {'neig': 10000, 'elo': 0, 'level': 0}

def save_user_data(username, neig, elo, level):
    conn = sqlite3.connect(DATABASE_PATH)
    c = conn.cursor()
    c.execute('INSERT OR REPLACE INTO wallets (username, neig, elo, level) VALUES (?, ?, ?, ?)', (username, neig, elo, level))
    conn.commit()
    conn.close()

def calculate_level(elo):
    return elo // 1000

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

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/register', methods=['POST'])
def register():
    username = request.form.get('username')
    password = request.form.get('password')
    avatar = request.files.get('avatar')
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
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        c = conn.cursor()
        c.execute('INSERT INTO users (username, password, avatar) VALUES (?, ?, ?)', (username, hashed_password, avatar_path))
        c.execute('INSERT OR IGNORE INTO wallets (username, neig, elo, level) VALUES (?, 10000, 0, 0)', (username,))
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

@app.route('/test_stockfish')
def test_stockfish():
    try:
        with chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH) as engine:
            return jsonify({'status': 'Stockfish OK'})
    except Exception as e:
        return jsonify({'status': 'Error', 'message': str(e)})

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
        session['username'] = username
        avatar = result[1] or '/static/default-avatar.png'
        user_data = load_user_data(username)
        emit('login_success', {'username': username, 'avatar': avatar, 'neig': user_data['neig'], 'elo': user_data['elo'], 'level': user_data['level']}, to=sid)
        online_players[sid] = {'username': username, 'avatar': avatar}
        socketio.emit('online_players_update', list(online_players.values()))
    else:
        emit('login_error', {'error': 'Usuario o contraseña incorrectos'}, to=sid)

@socketio.on('logout')
def on_logout(data):
    sid = request.sid
    username = data.get('username')
    if sid in sessions and sessions[sid] == username:
        del sessions[sid]
        if sid in online_players:
            del online_players[sid]
        if sid in available_players:
            del available_players[sid]
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
        socketio.emit('online_players_update', list(online_players.values()))
        socketio.emit('waitlist_update', {'players': [{'sid': s, 'username': info['username'], 'chosen_color': info['chosen_color']} for s, info in available_players.items()]})
        session.pop('username', None)

@socketio.on('connect')
def on_connect():
    sid = request.sid
    username = session.get('username') or sessions.get(sid)
    if username:
        sessions[sid] = username
        conn = sqlite3.connect(DATABASE_PATH)
        c = conn.cursor()
        c.execute('SELECT avatar FROM users WHERE username = ?', (username,))
        result = c.fetchone()
        avatar = result[0] if result else '/static/default-avatar.png'
        conn.close()
        online_players[sid] = {'username': username, 'avatar': avatar}
        socketio.emit('online_players_update', list(online_players.values()))
        user_data = load_user_data(username)
        emit('user_data_update', {'neig': user_data['neig'], 'elo': user_data['elo'], 'level': user_data['level']}, to=sid)

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

@socketio.on('join_user_room')
def on_join_user_room(data):
    username = data['username']
    join_room(username)

@socketio.on('join')
def on_join(data):
    room = data['room']
    sid = request.sid
    timer_minutes = int(data.get('timer', 0))
    chosen_color = data.get('color', '#FFFFFF')
    username = sessions.get(sid)
    if not username:
        emit('error', {'message': 'Debes iniciar sesión'}, to=sid)
        return

    join_room(room)

    if room not in players:
        players[room] = {}

    if len(players[room]) >= 2:
        emit('error', {'message': 'La sala está llena'}, to=sid)
        leave_room(room)
        return

    players[room][sid] = {
        'color': 'white' if len(players[room]) == 0 else 'black',
        'chosen_color': chosen_color,
        'username': username
    }
    emit('color_assigned', {'color': players[room][sid]['color'], 'chosenColor': chosen_color}, to=sid)

    if room not in games:
        board = reset_board()
        games[room] = {
            'chessboard': board,
            'turn': 'white',
            'time_white': timer_minutes * 60 if timer_minutes > 0 else None,
            'time_black': timer_minutes * 60 if timer_minutes > 0 else None,
            'last_move_time': time.time() if timer_minutes > 0 else None
        }

    if len(players[room]) == 2:
        time_per_player = timer_minutes * 60 if timer_minutes > 0 else None
        if time_per_player:
            games[room]['time_white'] = time_per_player
            games[room]['time_black'] = time_per_player
            games[room]['last_move_time'] = time.time()

        player_colors = {players[room][sid]['color']: players[room][sid]['chosen_color'] for sid in players[room]}
        board_state = [['.' for _ in range(8)] for _ in range(8)]
        for square in chess.SQUARES:
            piece = games[room]['chessboard'].piece_at(square)
            if piece:
                row, col = 7 - (square // 8), square % 8
                board_state[row][col] = piece.symbol()

        socketio.emit('game_start', {
            'board': board_state,
            'turn': games[room]['turn'],
            'time_white': games[room]['time_white'],
            'time_black': games[room]['time_black'],
            'playerColors': player_colors
        }, room=room)
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
        join_room(room)
        board_state = [['.' for _ in range(8)] for _ in range(8)]
        for square in chess.SQUARES:
            piece = games[room]['chessboard'].piece_at(square)
            if piece:
                row, col = 7 - (square // 8), square % 8
                board_state[row][col] = piece.symbol()
        emit('game_start', {
            'board': board_state,
            'turn': games[room]['turn'],
            'time_white': games[room]['time_white'],
            'time_black': games[room]['time_black'],
            'playerColors': {players[room][sid]['color']: players[room][sid]['chosen_color'] for sid in players[room]}
        }, to=sid)

@socketio.on('play_with_bot')
def on_play_with_bot(data):
    sid = request.sid
    username = sessions.get(sid)
    if not username:
        emit('error', {'message': 'Debes iniciar sesión'}, to=sid)
        return

    timer_minutes = int(data.get('timer', 0))
    chosen_color = data.get('color', '#FFFFFF')
    difficulty = data.get('difficulty', 'medium')
    player_color = data.get('player_color', 'white')
    bot_color = 'black' if player_color == 'white' else 'white'
    bot_name = 'Stockfish'

    room = f"bot_{sid}_{str(uuid.uuid4())}"
    join_room(room)

    players[room] = {
        sid: {'color': player_color, 'chosen_color': chosen_color, 'username': username},
        'bot': {'color': bot_color, 'chosen_color': '#000000', 'username': bot_name}
    }

    board = reset_board()
    games[room] = {
        'chessboard': board,
        'turn': 'white',
        'time_white': timer_minutes * 60 if timer_minutes > 0 else None,
        'time_black': timer_minutes * 60 if timer_minutes > 0 else None,
        'last_move_time': time.time() if timer_minutes > 0 else None,
        'is_bot_game': True,
        'difficulty': difficulty
    }

    board_state = [['.' for _ in range(8)] for _ in range(8)]
    for square in chess.SQUARES:
        piece = board.piece_at(square)
        if piece:
            row, col = 7 - (square // 8), square % 8
            board_state[row][col] = piece.symbol()

    emit('color_assigned', {'color': player_color, 'chosenColor': chosen_color}, to=sid)
    player_colors = {
        player_color: chosen_color,
        bot_color: '#000000'
    }
    socketio.emit('game_start', {
        'board': board_state,
        'turn': 'white',
        'time_white': games[room]['time_white'],
        'time_black': games[room]['time_black'],
        'playerColors': player_colors,
        'room': room,
        'is_bot_game': True
    }, room=room)

    if player_color == 'black':
        try:
            make_bot_move(room, sid)
        except Exception as e:
            print(f"Error al iniciar movimiento del bot: {str(e)}")
            emit('error', {'message': 'Error al iniciar el movimiento del bot'}, to=sid)

def make_bot_move(room, sid):
    if room not in games or not games[room].get('is_bot_game'):
        return

    difficulty = games[room].get('difficulty', 'medium')
    if difficulty == 'easy':
        skill_level = 0
        think_time = 0.05
    elif difficulty == 'hard':
        skill_level = 20
        think_time = 1.0
    else:
        skill_level = 10
        think_time = 0.1

    board = games[room]['chessboard']
    try:
        with chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH) as engine:
            engine.configure({"Skill Level": skill_level})
            result = engine.play(board, chess.engine.Limit(time=think_time))
            move = result.move
            board.push(move)
            games[room]['turn'] = 'black' if games[room]['turn'] == 'white' else 'white'

            board_state = [['.' for _ in range(8)] for _ in range(8)]
            for square in chess.SQUARES:
                piece = board.piece_at(square)
                if piece:
                    row, col = 7 - (square // 8), square % 8
                    board_state[row][col] = piece.symbol()

            update_timer(room)
            socketio.emit('update_board', {'board': board_state, 'turn': games[room]['turn']}, room=room)

            if board.is_check():
                socketio.emit('check', {'message': '¡Jaque!'}, room=room)
                if board.is_checkmate():
                    winner_username = sessions[sid] if games[room]['turn'] != players[room][sid]['color'] else 'Stockfish'
                    user_data = load_user_data(sessions[sid])
                    elo_points = 50 if difficulty == 'easy' else 100 if difficulty == 'medium' else 150
                    neig_points = 25 if difficulty == 'easy' else 50 if difficulty == 'medium' else 75
                    if winner_username == sessions[sid]:
                        user_data['elo'] += elo_points
                        user_data['neig'] += neig_points
                        user_data['level'] = calculate_level(user_data['elo'])
                        save_user_data(sessions[sid], user_data['neig'], user_data['elo'], user_data['level'])
                        emit('user_data_update', {'neig': user_data['neig'], 'elo': user_data['elo'], 'level': user_data['level']}, to=sid)
                    socketio.emit('game_over', {
                        'message': f'¡Jaque mate! Gana {winner_username}',
                        'elo_points': elo_points if winner_username == sessions[sid] else 0,
                        'neig_points': neig_points if winner_username == sessions[sid] else 0
                    }, room=room)
                    del players[room]
                    del games[room]
                elif board.is_stalemate() or board.is_insufficient_material() or board.is_seventyfive_moves() or board.is_fivefold_repetition():
                    socketio.emit('game_over', {'message': '¡Partida terminada en tablas!'}, room=room)
                    del players[room]
                    del games[room]
    except Exception as e:
        print(f"Error al ejecutar Stockfish en la sala {room}: {str(e)}")
        socketio.emit('error', {'message': f'Error al generar el movimiento del bot: {str(e)}'}, room=room)

@socketio.on('move')
def on_move(data):
    from_square = data['from']
    to_square = data['to']
    promotion = data.get('promotion')
    room = data['room']
    
    if room not in games:
        emit('error', {'message': 'Sala no encontrada'}, room=room)
        return
    
    game = games[room]
    sid = request.sid
    chessboard = game['chessboard']
    
    move_uci = from_square + to_square
    if promotion:
        move_uci += promotion.lower()
    
    try:
        move = chess.Move.from_uci(move_uci)
    except ValueError:
        emit('error', {'message': 'Movimiento inválido'}, room=room)
        return
    
    if move in chessboard.legal_moves:
        chessboard.push(move)
        game['turn'] = 'black' if game['turn'] == 'white' else 'white'
        
        board_state = [['.' for _ in range(8)] for _ in range(8)]
        for square in chess.SQUARES:
            piece = chessboard.piece_at(square)
            if piece:
                row, col = 7 - (square // 8), square % 8
                board_state[row][col] = piece.symbol()
        
        update_timer(room)
        socketio.emit('update_board', {
            'board': board_state,
            'turn': game['turn']
        }, room=room)
        
        if chessboard.is_check():
            socketio.emit('check', {'message': '¡Jaque!'}, room=room)
            if chessboard.is_checkmate():
                winner_username = sessions[sid] if game['turn'] != players[room][sid]['color'] else 'Stockfish' if game.get('is_bot_game') else sessions[[s for s in players[room] if s != sid][0]]
                user_data = load_user_data(sessions[sid])
                elo_points = 50 if not game.get('is_bot_game') else (50 if game['difficulty'] == 'easy' else 100 if game['difficulty'] == 'medium' else 150)
                neig_points = 25 if not game.get('is_bot_game') else (25 if game['difficulty'] == 'easy' else 50 if game['difficulty'] == 'medium' else 75)
                if winner_username == sessions[sid]:
                    user_data['elo'] += elo_points
                    user_data['neig'] += neig_points
                    user_data['level'] = calculate_level(user_data['elo'])
                    save_user_data(sessions[sid], user_data['neig'], user_data['elo'], user_data['level'])
                    emit('user_data_update', {'neig': user_data['neig'], 'elo': user_data['elo'], 'level': user_data['level']}, to=sid)
                socketio.emit('game_over', {
                    'message': f'¡Jaque mate! Gana {winner_username}',
                    'elo_points': elo_points if winner_username == sessions[sid] else 0,
                    'neig_points': neig_points if winner_username == sessions[sid] else 0
                }, room=room)
                del players[room]
                del games[room]
                return
            elif chessboard.is_stalemate() or chessboard.is_insufficient_material() or chessboard.is_seventyfive_moves() or chessboard.is_fivefold_repetition():
                socketio.emit('game_over', {'message': '¡Partida terminada en tablas!'}, room=room)
                del players[room]
                del games[room]
                return
        
        if game.get('is_bot_game') and game['turn'] != players[room][sid]['color']:
            try:
                make_bot_move(room, sid)
            except Exception as e:
                print(f"Error al procesar movimiento del bot tras jugada del usuario: {str(e)}")
                emit('error', {'message': 'Error al procesar el movimiento del bot'}, room=room)
    else:
        emit('error', {'message': 'Movimiento ilegal'}, room=room)

@socketio.on('resign')
def on_resign(data):
    room = data['room']
    sid = request.sid
    if room in players and sid in players[room]:
        user_data = load_user_data(sessions[sid])
        elo_points = 50 if not games[room].get('is_bot_game') else (50 if games[room]['difficulty'] == 'easy' else 100 if games[room]['difficulty'] == 'medium' else 150)
        neig_points = 25 if not games[room].get('is_bot_game') else (25 if games[room]['difficulty'] == 'easy' else 50 if games[room]['difficulty'] == 'medium' else 75)
        if games[room].get('is_bot_game'):
            user_data['elo'] = max(0, user_data['elo'] - elo_points)
            user_data['neig'] = max(0, user_data['neig'] - neig_points)
            user_data['level'] = calculate_level(user_data['elo'])
            save_user_data(sessions[sid], user_data['neig'], user_data['elo'], user_data['level'])
            emit('user_data_update', {'neig': user_data['neig'], 'elo': user_data['elo'], 'level': user_data['level']}, to=sid)
            emit('resigned', {
                'message': f'Abandonaste la partida contra Stockfish. Perdiste {elo_points} ELO y {neig_points} Neig.',
                'elo': user_data['elo'],
                'neig': user_data['neig'],
                'level': user_data['level']
            }, to=sid)
        else:
            winner_sid = [s for s in players[room] if s != sid][0]
            winner_username = sessions[winner_sid]
            loser_username = sessions[sid]
            winner_data = load_user_data(winner_username)
            loser_data = load_user_data(loser_username)
            winner_data['elo'] += elo_points
            winner_data['neig'] += neig_points
            winner_data['level'] = calculate_level(winner_data['elo'])
            loser_data['elo'] = max(0, loser_data['elo'] - elo_points)
            loser_data['neig'] = max(0, loser_data['neig'] - neig_points)
            loser_data['level'] = calculate_level(loser_data['elo'])
            save_user_data(winner_username, winner_data['neig'], winner_data['elo'], winner_data['level'])
            save_user_data(loser_username, loser_data['neig'], loser_data['elo'], loser_data['level'])
            emit('user_data_update', {'neig': winner_data['neig'], 'elo': winner_data['elo'], 'level': winner_data['level']}, to=winner_sid)
            emit('user_data_update', {'neig': loser_data['neig'], 'elo': loser_data['elo'], 'level': loser_data['level']}, to=sid)
            emit('resigned', {
                'message': f'Oponente abandonó. Ganaste {elo_points} ELO y {neig_points} Neig.',
                'elo': winner_data['elo'],
                'neig': winner_data['neig'],
                'level': winner_data['level']
            }, to=winner_sid)
            emit('resigned', {
                'message': f'Abandonaste la partida. Perdiste {elo_points} ELO y {neig_points} Neig.',
                'elo': loser_data['elo'],
                'neig': loser_data['neig'],
                'level': loser_data['level']
            }, to=sid)
        if room in players:
            del players[room]
        if room in games:
            del games[room]

@socketio.on('leave')
def on_leave(data):
    room = data['room']
    sid = request.sid
    if room in players and sid in players[room]:
        del players[room][sid]
        if not players[room]:
            del players[room]
            if room in games:
                del games[room]
        else:
            socketio.emit('player_left', {'message': 'El oponente abandonó la partida'}, room=room)
        leave_room(room)

@socketio.on('chat_message')
def on_chat_message(data):
    room = data['room']
    message = data['message']
    sid = request.sid
    if room in players and sid in players[room]:
        socketio.emit('new_message', {'color': players[room][sid]['color'], 'message': message}, room=room)

@socketio.on('audio_message')
def on_audio_message(data):
    room = data['room']
    audio = data['audio']
    sid = request.sid
    if room in players and sid in players[room]:
        socketio.emit('audio_message', {'color': players[room][sid]['color'], 'audio': audio}, room=room)

@socketio.on('video_signal')
def on_video_signal(data):
    room = data['room']
    signal = data['signal']
    sid = request.sid
    if room in players and sid in players[room]:
        socketio.emit('video_signal', {'signal': signal}, room=room, skip_sid=sid)

@socketio.on('video_stop')
def on_video_stop(data):
    room = data['room']
    socketio.emit('video_stop', {}, room=room)

@socketio.on('save_game')
def on_save_game(data):
    room = data['room']
    game_name = data['game_name']
    sid = request.sid
    username = sessions.get(sid)
    if not username:
        emit('error', {'message': 'Debes iniciar sesión'}, to=sid)
        return
    if room not in games:
        emit('error', {'message': 'Sala no encontrada'}, to=sid)
        return
    conn = sqlite3.connect(DATABASE_PATH)
    c = conn.cursor()
    c.execute('INSERT INTO saved_games (username, room, game_name, fen, turn) VALUES (?, ?, ?, ?, ?)',
              (username, room, game_name, games[room]['chessboard'].fen(), games[room]['turn']))
    conn.commit()
    conn.close()
    emit('game_saved', {'message': f'Partida "{game_name}" guardada exitosamente'})

@socketio.on('get_saved_games')
def on_get_saved_games(data):
    username = data['username']
    sid = request.sid
    if not username or username != sessions.get(sid):
        emit('error', {'message': 'No autorizado'}, to=sid)
        return
    conn = sqlite3.connect(DATABASE_PATH)
    c = conn.cursor()
    c.execute('SELECT room, game_name, fen, turn FROM saved_games WHERE username = ?', (username,))
    games_list = [{'room': row[0], 'game_name': row[1], 'fen': row[2], 'turn': row[3]} for row in c.fetchall()]
    conn.close()
    emit('saved_games_list', {'games': games_list}, to=sid)

@socketio.on('load_game')
def on_load_game(data):
    username = data['username']
    game_name = data['game_name']
    sid = request.sid
    if not username or username != sessions.get(sid):
        emit('error', {'message': 'No autorizado'}, to=sid)
        return
    conn = sqlite3.connect(DATABASE_PATH)
    c = conn.cursor()
    c.execute('SELECT room, fen, turn FROM saved_games WHERE username = ? AND game_name = ?', (username, game_name))
    result = c.fetchone()
    conn.close()
    if result:
        room, fen, turn = result
        board = chess.Board(fen)
        board_state = [['.' for _ in range(8)] for _ in range(8)]
        for square in chess.SQUARES:
            piece = board.piece_at(square)
            if piece:
                row, col = 7 - (square // 8), square % 8
                board_state[row][col] = piece.symbol()
        games[room] = {
            'chessboard': board,
            'turn': turn,
            'time_white': None,
            'time_black': None
        }
        players[room] = {sid: {'color': 'white', 'chosen_color': '#FFFFFF', 'username': username}}
        join_room(room)
        emit('game_loaded', {
            'room': room,
            'board': board_state,
            'turn': turn,
            'game_name': game_name
        }, to=sid)

@socketio.on('join_waitlist')
def on_join_waitlist(data):
    sid = request.sid
    username = sessions.get(sid)
    chosen_color = data.get('color', '#FFFFFF')
    avatar = data.get('avatar', '/static/default-avatar.png')
    if username and sid not in available_players:
        available_players[sid] = {'username': username, 'chosen_color': chosen_color, 'avatar': avatar}
        socketio.emit('waitlist_update', {
            'players': [{'sid': s, 'username': info['username'], 'chosen_color': info['chosen_color'], 'avatar': info['avatar']} for s, info in available_players.items()]
        })

@socketio.on('leave_waitlist')
def on_leave_waitlist():
    sid = request.sid
    if sid in available_players:
        del available_players[sid]
        socketio.emit('waitlist_update', {
            'players': [{'sid': s, 'username': info['username'], 'chosen_color': info['chosen_color'], 'avatar': info['avatar']} for s, info in available_players.items()]
        })

@socketio.on('select_opponent')
def on_select_opponent(data):
    sid = request.sid
    opponent_sid = data['opponent_sid']
    if opponent_sid in available_players and sid in available_players:
        room = f"private_{sid}_{opponent_sid}"
        username = sessions[sid]
        opponent_username = available_players[opponent_sid]['username']
        join_room(room, sid)
        join_room(room, opponent_sid)
        emit('private_chat_start', {'room': room, 'opponent': opponent_username}, to=sid)
        emit('private_chat_start', {'room': room, 'opponent': username}, to=opponent_sid)
        del available_players[sid]
        del available_players[opponent_sid]
        socketio.emit('waitlist_update', {
            'players': [{'sid': s, 'username': info['username'], 'chosen_color': info['chosen_color'], 'avatar': info['avatar']} for s, info in available_players.items()]
        })

@socketio.on('private_message')
def on_private_message(data):
    room = data['room']
    message = data['message']
    sid = request.sid
    username = sessions.get(sid)
    socketio.emit('private_message', {'username': username, 'message': message}, room=room)

@socketio.on('accept_conditions')
def on_accept_conditions(data):
    room = data['room']
    sid = request.sid
    username = sessions.get(sid)
    if room not in players:
        players[room] = {}
    players[room][sid] = {'color': 'white' if len(players[room]) == 0 else 'black', 'chosen_color': '#FFFFFF', 'username': username}
    if len(players[room]) == 2:
        board = reset_board()
        board_state = [['.' for _ in range(8)] for _ in range(8)]
        for square in chess.SQUARES:
            piece = board.piece_at(square)
            if piece:
                row, col = 7 - (square // 8), square % 8
                board_state[row][col] = piece.symbol()
        games[room] = {
            'chessboard': board,
            'turn': 'white',
            'time_white': None,
            'time_black': None
        }
        player_colors = {players[room][s]['color']: players[room][s]['chosen_color'] for s in players[room]}
        socketio.emit('game_start', {
            'board': board_state,
            'turn': 'white',
            'time_white': None,
            'time_black': None,
            'playerColors': player_colors
        }, room=room)

@socketio.on('leave_private_chat')
def on_leave_private_chat(data):
    room = data['room']
    sid = request.sid
    leave_room(room)
    if room in players:
        del players[room]
    if room in games:
        del games[room]

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=int(os.getenv('PORT', 10000)))
