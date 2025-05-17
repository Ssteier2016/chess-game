import os
import eventlet
import logging
from logging.handlers import RotatingFileHandler
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
import random
from datetime import datetime

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
handler = RotatingFileHandler('app.log', maxBytes=1000000, backupCount=5)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)

app = Flask(__name__, static_folder='static', template_folder='templates')
app.secret_key = os.getenv('SECRET_KEY', 'Ma730yIan')
socketio = SocketIO(app, cors_allowed_origins="*")
DATABASE_PATH = '/opt/render/project/src/users.db' if os.getenv('RENDER') else 'users.db'
STOCKFISH_PATH = os.path.join(os.path.dirname(__file__), 'src', 'stockfish') if os.getenv('RENDER') else 'src/stockfish'

# Verificar si Stockfish existe
if not os.path.exists(STOCKFISH_PATH):
    logger.error(f"No se encontró Stockfish en {STOCKFISH_PATH}")
    raise FileNotFoundError(f"Stockfish no encontrado en {STOCKFISH_PATH}")

# Mensajes del bot para el chat
BOT_MESSAGES = {
    'start': [
        "¡Vamos a jugar! ¿Preparado para un desafío?",
        "Soy Stockfish, tu oponente. ¡Hagamos una gran partida!",
        "¡Empecemos! Espero que traigas tu mejor estrategia."
    ],
    'move': [
        "Buen movimiento, pero veamos cómo respondes a esto.",
        "Interesante jugada. Aquí va la mía.",
        "¡No está mal! Mi turno.",
        "¿Eso es todo? Aquí tienes mi respuesta."
    ],
    'check': [
        "¡Jaque! ¿Cómo vas a salir de esta?",
        "Estás en jaque. Piensa con cuidado.",
        "¡Jaque! Vamos, sorpréndeme."
    ],
    'checkmate': [
        "¡Jaque mate! ¡Gran partida!",
        "¡Jaque mate! Lo diste todo, ¿eh?",
        "¡Jaque mate! Hasta la próxima."
    ],
    'stalemate': [
        "Tablas, ¡qué partida tan equilibrada!",
        "¡Empate! Nadie se rindió hoy.",
        "Tablas, ¡bien jugado!"
    ]
}

sessions = {}
players = {}
games = {}
online_players = {}
available_players = {}

def board_to_fen(board, turn, game_type='chess'):
    """Convertir el tablero interno a notación FEN (solo para ajedrez)."""
    if game_type != 'chess':
        return json.dumps(board)
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

def fen_to_board(fen, game_type='chess'):
    """Convertir notación FEN a tablero interno."""
    if game_type != 'chess':
        return json.loads(fen), 'white'
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

def reset_chess_board():
    """Inicializar tablero de ajedrez."""
    return chess.Board()

def initialize_checkers_board():
    """Inicializar tablero de damas."""
    board = [['.' for _ in range(8)] for _ in range(8)]
    for row in [0, 1, 2]:
        for col in range(8):
            if (row + col) % 2 == 1:
                board[row][col] = 'b'  # Fichas negras
    for row in [5, 6, 7]:
        for col in range(8):
            if (row + col) % 2 == 1:
                board[row][col] = 'w'  # Fichas blancas
    return board

def init_db():
    """Inicializar la base de datos."""
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY, 
            password BLOB, 
            avatar TEXT
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS saved_games (
            username TEXT, 
            room TEXT, 
            game_name TEXT, 
            fen TEXT, 
            turn TEXT, 
            game_type TEXT
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS wallets (
            username TEXT PRIMARY KEY, 
            neig REAL DEFAULT 10000, 
            elo INTEGER DEFAULT 0, 
            level INTEGER DEFAULT 0
        )''')
        conn.commit()
        logger.info("Base de datos inicializada correctamente")
    except Exception as e:
        logger.error(f"Error al inicializar la base de datos: {str(e)}")
        raise
    finally:
        conn.close()

init_db()

def load_user_data(username):
    """Cargar datos del usuario desde la base de datos."""
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        c = conn.cursor()
        c.execute('SELECT neig, elo, level FROM wallets WHERE username = ?', (username,))
        result = c.fetchone()
        return {'neig': result[0], 'elo': result[1], 'level': result[2]} if result else {'neig': 10000, 'elo': 0, 'level': 0}
    except Exception as e:
        logger.error(f"Error al cargar datos del usuario {username}: {str(e)}")
        return {'neig': 10000, 'elo': 0, 'level': 0}
    finally:
        conn.close()

def save_user_data(username, neig, elo, level):
    """Guardar datos del usuario en la base de datos."""
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        c = conn.cursor()
        c.execute('INSERT OR REPLACE INTO wallets (username, neig, elo, level) VALUES (?, ?, ?, ?)', 
                  (username, neig, elo, level))
        conn.commit()
        logger.info(f"Datos del usuario {username} guardados: neig={neig}, elo={elo}, level={level}")
    except Exception as e:
        logger.error(f"Error al guardar datos del usuario {username}: {str(e)}")
    finally:
        conn.close()

def calculate_level(elo):
    """Calcular el nivel basado en el ELO."""
    return elo // 1000

def update_timer(room):
    """Actualizar el temporizador del juego."""
    if room in games and games[room]['time_white'] is not None:
        try:
            current_time = time.time()
            if games[room]['last_move_time']:
                elapsed = current_time - games[room]['last_move_time']
                if games[room]['turn'] == 'white':
                    games[room]['time_white'] = max(0, games[room]['time_white'] - elapsed)
                else:
                    games[room]['time_black'] = max(0, games[room]['time_black'] - elapsed)
            games[room]['last_move_time'] = current_time
            socketio.emit('timer_update', {
                'time_white': games[room]['time_white'], 
                'time_black': games[room]['time_black']
            }, room=room)
            if games[room]['time_white'] <= 0:
                winner = 'black'
                socketio.emit('game_over', {'message': '¡Tiempo agotado! Gana negras'}, room=room)
                end_game(room, winner)
                logger.info(f"Tiempo agotado en sala {room}: Ganaron las negras")
            elif games[room]['time_black'] <= 0:
                winner = 'white'
                socketio.emit('game_over', {'message': '¡Tiempo agotado! Gana blancas'}, room=room)
                end_game(room, winner)
                logger.info(f"Tiempo agotado en sala {room}: Ganaron las blancas")
        except Exception as e:
            logger.error(f"Error al actualizar el temporizador en la sala {room}: {str(e)}")

def end_game(room, winner=None):
    """Finalizar un juego y actualizar datos de los usuarios."""
    if room not in games or room not in players:
        return
    try:
        game = games[room]
        is_bot_game = game.get('is_bot_game', False)
        if is_bot_game:
            player_sid = next(sid for sid in players[room] if sid != 'bot')
            player_username = sessions.get(player_sid)
            user_data = load_user_data(player_username)
            elo_points = 50 if game['difficulty'] == 'easy' else 100 if game['difficulty'] == 'medium' else 150
            neig_points = 25 if game['difficulty'] == 'easy' else 50 if game['difficulty'] == 'medium' else 75
            if winner and players[room][player_sid]['color'] == winner:
                user_data['elo'] += elo_points
                user_data['neig'] += neig_points
                user_data['level'] = calculate_level(user_data['elo'])
                save_user_data(player_username, user_data['neig'], user_data['elo'], user_data['level'])
                socketio.emit('user_data_update', {
                    'neig': user_data['neig'], 
                    'elo': user_data['elo'], 
                    'level': user_data['level']
                }, to=player_sid)
                socketio.emit('game_over', {
                    'message': f'¡Jaque mate! Gana {player_username}',
                    'elo_points': elo_points,
                    'neig_points': neig_points,
                    'neig': user_data['neig'],
                    'elo': user_data['elo'],
                    'level': user_data['level']
                }, room=room)
            else:
                socketio.emit('game_over', {
                    'message': '¡Jaque mate! Gana Stockfish',
                    'elo_points': 0,
                    'neig_points': 0
                }, room=room)
        else:
            player_sids = list(players[room].keys())
            if len(player_sids) == 2:
                winner_sid = next(sid for sid in player_sids if players[room][sid]['color'] == winner) if winner else None
                loser_sid = next(sid for sid in player_sids if sid != winner_sid) if winner_sid else None
                elo_points = 50
                neig_points = 25
                if winner_sid:
                    winner_username = sessions.get(winner_sid)
                    loser_username = sessions.get(loser_sid)
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
                    socketio.emit('user_data_update', {
                        'neig': winner_data['neig'], 
                        'elo': winner_data['elo'], 
                        'level': winner_data['level']
                    }, to=winner_sid)
                    socketio.emit('user_data_update', {
                        'neig': loser_data['neig'], 
                        'elo': loser_data['elo'], 
                        'level': loser_data['level']
                    }, to=loser_sid)
                    socketio.emit('game_over', {
                        'message': f'¡Partida terminada! Gana {winner_username}',
                        'elo_points': elo_points,
                        'neig_points': neig_points,
                        'neig': winner_data['neig'],
                        'elo': winner_data['elo'],
                        'level': winner_data['level']
                    }, to=winner_sid)
                    socketio.emit('game_over', {
                        'message': f'¡Partida terminada! Pierde {loser_username}',
                        'elo_points': -elo_points,
                        'neig_points': -neig_points,
                        'neig': loser_data['neig'],
                        'elo': loser_data['elo'],
                        'level': loser_data['level']
                    }, to=loser_sid)
        del players[room]
        del games[room]
    except Exception as e:
        logger.error(f"Error al finalizar juego en sala {room}: {str(e)}")

@app.route('/')
def index():
    """Ruta principal que sirve el archivo index.html."""
    logger.info("Sirviendo index.html")
    return render_template('index.html')

@app.route('/register', methods=['POST'])
def register():
    """Registrar un nuevo usuario."""
    try:
        username = request.form.get('username')
        password = request.form.get('password')
        avatar = request.files.get('avatar')
        if not username or not password:
            logger.warning("Intento de registro sin usuario o contraseña")
            return jsonify({'error': 'Usuario y contraseña requeridos'}), 400
        hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
        avatar_path = '/static/default-avatar.png'
        if avatar:
            avatar_dir = os.path.join(app.root_path, 'static', 'avatars')
            os.makedirs(avatar_dir, exist_ok=True)
            avatar_filename = f"{username}_avatar{os.path.splitext(avatar.filename)[1]}"
            avatar_path = f"/static/avatars/{avatar_filename}"
            avatar.save(os.path.join(avatar_dir, avatar_filename))
        conn = sqlite3.connect(DATABASE_PATH)
        c = conn.cursor()
        c.execute('INSERT INTO users (username, password, avatar) VALUES (?, ?, ?)', 
                  (username, hashed_password, avatar_path))
        c.execute('INSERT OR IGNORE INTO wallets (username, neig, elo, level) VALUES (?, 10000, 0, 0)', 
                  (username,))
        conn.commit()
        logger.info(f"Usuario {username} registrado exitosamente")
        return jsonify({'success': True, 'username': username, 'avatar': avatar_path})
    except sqlite3.IntegrityError:
        logger.warning(f"Intento de registro con usuario existente: {username}")
        return jsonify({'error': 'El usuario ya existe'}), 400
    except Exception as e:
        logger.error(f"Error durante el registro: {str(e)}")
        return jsonify({'error': 'Error interno del servidor'}), 500
    finally:
        conn.close()

@app.route('/get_avatar')
def get_avatar():
    """Obtener el avatar de un usuario."""
    try:
        username = request.args.get('username')
        conn = sqlite3.connect(DATABASE_PATH)
        c = conn.cursor()
        c.execute('SELECT avatar FROM users WHERE username = ?', (username,))
        result = c.fetchone()
        avatar = result[0] if result else '/static/default-avatar.png'
        logger.info(f"Avatar recuperado para {username}: {avatar}")
        return jsonify({'avatar': avatar})
    except Exception as e:
        logger.error(f"Error al recuperar avatar para {username}: {str(e)}")
        return jsonify({'avatar': '/static/default-avatar.png'})
    finally:
        conn.close()

@app.route('/test_stockfish')
def test_stockfish():
    """Probar la conexión con Stockfish."""
    try:
        with chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH) as engine:
            logger.info("Prueba de Stockfish exitosa")
            return jsonify({'status': 'Stockfish OK'})
    except Exception as e:
        logger.error(f"Prueba de Stockfish fallida: {str(e)}")
        return jsonify({'status': 'Error', 'message': str(e)})

@socketio.on('login')
def on_login(data):
    """Manejar el inicio de sesión del usuario."""
    sid = request.sid
    try:
        username = data['username']
        password = data['password']
        conn = sqlite3.connect(DATABASE_PATH)
        c = conn.cursor()
        c.execute('SELECT password, avatar FROM users WHERE username = ?', (username,))
        result = c.fetchone()
        if result and bcrypt.checkpw(password.encode('utf-8'), result[0]):
            sessions[sid] = username
            session['username'] = username
            avatar = result[1] or '/static/default-avatar.png'
            user_data = load_user_data(username)
            emit('login_success', {
                'username': username,
                'avatar': avatar,
                'neig': user_data['neig'],
                'elo': user_data['elo'],
                'level': user_data['level']
            }, to=sid)
            online_players[sid] = {'username': username, 'avatar': avatar}
            socketio.emit('online_players_update', list(online_players.values()))
            logger.info(f"Usuario {username} inició sesión exitosamente")
        else:
            emit('login_error', {'error': 'Usuario o contraseña incorrectos'}, to=sid)
            logger.warning(f"Intento de inicio de sesión fallido para {username}")
    except Exception as e:
        logger.error(f"Error durante el inicio de sesión para {username}: {str(e)}")
        emit('login_error', {'error': 'Error interno del servidor'}, to=sid)
    finally:
        conn.close()

@socketio.on('logout')
def on_logout(data):
    """Manejar el cierre de sesión del usuario."""
    sid = request.sid
    try:
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
            socketio.emit('waitlist_update', {
                'players': [{'sid': s, 'username': info['username'], 'chosen_color': info['chosen_color'], 'avatar': info['avatar']} for s, info in available_players.items()]
            })
            session.pop('username', None)
            logger.info(f"Usuario {username} cerró sesión")
    except Exception as e:
        logger.error(f"Error durante el cierre de sesión para {username}: {str(e)}")

@socketio.on('connect')
def on_connect():
    """Manejar la conexión de un cliente."""
    sid = request.sid
    try:
        username = session.get('username') or sessions.get(sid)
        if username:
            sessions[sid] = username
            conn = sqlite3.connect(DATABASE_PATH)
            c = conn.cursor()
            c.execute('SELECT avatar FROM users WHERE username = ?', (username,))
            result = c.fetchone()
            avatar = result[0] if result else '/static/default-avatar.png'
            online_players[sid] = {'username': username, 'avatar': avatar}
            socketio.emit('online_players_update', list(online_players.values()))
            user_data = load_user_data(username)
            emit('user_data_update', {
                'neig': user_data['neig'], 
                'elo': user_data['elo'], 
                'level': user_data['level']
            }, to=sid)
            logger.info(f"Usuario {username} conectado")
    except Exception as e:
        logger.error(f"Error durante la conexión para SID {sid}: {str(e)}")
    finally:
        if 'conn' in locals():
            conn.close()

@socketio.on('disconnect')
def on_disconnect():
    """Manejar la desconexión de un cliente."""
    sid = request.sid
    try:
        if sid in available_players:
            del available_players[sid]
            socketio.emit('waitlist_update', {
                'players': [{'sid': s, 'username': info['username'], 'chosen_color': info['chosen_color'], 'avatar': info['avatar']} for s, info in available_players.items()]
            })
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
            username = sessions[sid]
            del sessions[sid]
            logger.info(f"Usuario {username} desconectado")
    except Exception as e:
        logger.error(f"Error durante la desconexión para SID {sid}: {str(e)}")

@socketio.on('join_user_room')
def on_join_user_room(data):
    """Unirse a una sala de usuario."""
    try:
        username = data['username']
        join_room(username)
        logger.info(f"Usuario se unió a la sala {username}")
    except Exception as e:
        logger.error(f"Error al unirse a la sala de usuario: {str(e)}")

@socketio.on('join')
def on_join(data):
    """Unirse a una sala de juego."""
    sid = request.sid
    try:
        room = data['room']
        timer_minutes = int(data.get('timer', 0))
        chosen_color = data.get('color', '#FFFFFF')
        game_type = data.get('game_type', 'chess')
        username = sessions.get(sid)
        if not username:
            emit('error', {'message': 'Debes iniciar sesión'}, to=sid)
            logger.warning(f"Intento de unirse no autorizado a la sala {room}")
            return

        join_room(room)

        if room not in players:
            players[room] = {}

        if len(players[room]) >= 2:
            emit('error', {'message': 'La sala está llena'}, to=sid)
            leave_room(room)
            logger.warning(f"La sala {room} está llena")
            return

        players[room][sid] = {
            'color': 'white' if len(players[room]) == 0 else 'black',
            'chosen_color': chosen_color,
            'username': username
        }
        emit('color_assigned', {
            'color': players[room][sid]['color'], 
            'chosenColor': chosen_color
        }, to=sid)

        if room not in games:
            if game_type == 'chess':
                board = reset_chess_board()
            else:
                board = initialize_checkers_board()
            games[room] = {
                'board': board,
                'turn': 'white',
                'time_white': timer_minutes * 60 if timer_minutes > 0 else None,
                'time_black': timer_minutes * 60 if timer_minutes > 0 else None,
                'last_move_time': time.time() if timer_minutes > 0 else None,
                'game_type': game_type
            }

        if len(players[room]) == 2:
            time_per_player = timer_minutes * 60 if timer_minutes > 0 else None
            if time_per_player:
                games[room]['time_white'] = time_per_player
                games[room]['time_black'] = time_per_player
                games[room]['last_move_time'] = time.time()

            player_colors = {players[room][s]['color']: players[room][s]['chosen_color'] for s in players[room]}
            if game_type == 'chess':
                board_state = [['.' for _ in range(8)] for _ in range(8)]
                for square in chess.SQUARES:
                    piece = games[room]['board'].piece_at(square)
                    if piece:
                        row, col = 7 - (square // 8), square % 8
                        board_state[row][col] = piece.symbol()
            else:
                board_state = games[room]['board']

            socketio.emit('game_start', {
                'board': board_state,
                'turn': games[room]['turn'],
                'time_white': games[room]['time_white'],
                'time_black': games[room]['time_black'],
                'playerColors': player_colors,
                'room': room,
                'game_type': game_type
            }, room=room)
            logger.info(f"Juego iniciado en la sala {room} con {game_type}")
        else:
            emit('waiting_opponent', {'message': 'Esperando a otro jugador...'}, to=sid)
            logger.info(f"Usuario {username} esperando oponente en la sala {room}")
    except Exception as e:
        logger.error(f"Error al unirse a la sala {room}: {str(e)}")
        emit('error', {'message': 'Error interno del servidor'}, to=sid)

@socketio.on('global_chat_message')
def on_global_chat_message(data):
    """Manejar mensajes de texto en el chat global."""
    sid = request.sid
    try:
        username = sessions.get(sid)
        if not username:
            emit('error', {'message': 'Debes iniciar sesión para usar el chat global'}, to=sid)
            logger.warning(f"Intento no autorizado de mensaje global desde SID {sid}")
            return
        message = data['message']
        if message.strip():
            socketio.emit('new_global_message', {
                'username': username,
                'message': message,
                'timestamp': time.strftime('%H:%M:%S')
            })
            logger.info(f"Mensaje global de {username}: {message}")
    except Exception as e:
        logger.error(f"Error en el mensaje global: {str(e)}")

@socketio.on('global_audio_message')
def on_global_audio_message(data):
    """Manejar mensajes de voz en el chat global."""
    sid = request.sid
    try:
        username = sessions.get(sid)
        audio = data.get('audio')
        if not username:
            emit('error', {'message': 'Debes iniciar sesión para usar el chat global'}, to=sid)
            logger.warning(f"Intento no autorizado de mensaje de voz global desde SID {sid}")
            return
        if audio:
            socketio.emit('global_audio_message', {
                'username': username,
                'audio': audio,
                'timestamp': datetime.now().strftime('%H:%M:%S')
            })
            logger.info(f"Mensaje de voz global enviado por {username}")
    except Exception as e:
        logger.error(f"Error en el mensaje de voz global: {str(e)}")

@socketio.on('watch_game')
def on_watch_game(data):
    """Observar un juego en curso."""
    sid = request.sid
    try:
        room = data['room']
        game_type = data.get('game_type', 'chess')
        username = sessions.get(sid)
        if not username:
            emit('error', {'message': 'Debes iniciar sesión'}, to=sid)
            logger.warning(f"Intento no autorizado de observar juego en la sala {room}")
            return
        if room in games:
            join_room(room)
            if game_type == 'chess':
                board_state = [['.' for _ in range(8)] for _ in range(8)]
                for square in chess.SQUARES:
                    piece = games[room]['board'].piece_at(square)
                    if piece:
                        row, col = 7 - (square // 8), square % 8
                        board_state[row][col] = piece.symbol()
            else:
                board_state = games[room]['board']
            emit('game_start', {
                'board': board_state,
                'turn': games[room]['turn'],
                'time_white': games[room]['time_white'],
                'time_black': games[room]['time_black'],
                'playerColors': {players[room][s]['color']: players[room][s]['chosen_color'] for s in players[room] if s in players[room]},
                'game_type': game_type
            }, to=sid)
            logger.info(f"Usuario {username} observando juego en la sala {room}")
    except Exception as e:
        logger.error(f"Error al observar juego en la sala {room}: {str(e)}")

@socketio.on('play_with_bot')
def on_play_with_bot(data):
    """Iniciar un juego contra el bot."""
    sid = request.sid
    try:
        username = sessions.get(sid)
        if not username:
            emit('error', {'message': 'Debes iniciar sesión'}, to=sid)
            logger.warning(f"Intento no autorizado de juego con bot desde SID {sid}")
            return

        timer_minutes = int(data.get('timer', 0))
        chosen_color = data.get('color', '#FFFFFF')
        difficulty = data.get('difficulty', 'medium')
        player_color = data.get('player_color', 'white')
        game_type = data.get('game_type', 'chess')
        bot_color = 'black' if player_color == 'white' else 'white'
        bot_name = 'Stockfish'

        room = f"bot_{sid}_{str(uuid.uuid4())}"
        join_room(room)

        players[room] = {
            sid: {'color': player_color, 'chosen_color': chosen_color, 'username': username},
            'bot': {'color': bot_color, 'chosen_color': '#000000', 'username': bot_name}
        }

        if game_type == 'chess':
            board = reset_chess_board()
        else:
            emit('error', {'message': 'Juego con bot solo disponible para ajedrez'}, to=sid)
            logger.warning(f"Juego con bot solicitado para damas por {username}")
            return

        games[room] = {
            'board': board,
            'turn': 'white',
            'time_white': timer_minutes * 60 if timer_minutes > 0 else None,
            'time_black': timer_minutes * 60 if timer_minutes > 0 else None,
            'last_move_time': time.time() if timer_minutes > 0 else None,
            'is_bot_game': True,
            'difficulty': difficulty,
            'game_type': game_type
        }

        board_state = [['.' for _ in range(8)] for _ in range(8)]
        for square in chess.SQUARES:
            piece = board.piece_at(square)
            if piece:
                row, col = 7 - (square // 8), square % 8
                board_state[row][col] = piece.symbol()

        emit('color_assigned', {
            'color': player_color, 
            'chosenColor': chosen_color
        }, to=sid)
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
            'is_bot_game': True,
            'game_type': game_type
        }, room=room)

        socketio.emit('bot_chat_message', {
            'message': random.choice(BOT_MESSAGES['start'])
        }, room=room)
        logger.info(f"Juego con bot iniciado para {username} en la sala {room}")

        if player_color == 'black':
            make_bot_move(room, sid)
    except Exception as e:
        logger.error(f"Error al iniciar juego con bot para {username}: {str(e)}")
        emit('error', {'message': 'Error al iniciar el juego con bot'}, to=sid)

def make_bot_move(room, sid):
    """Realizar un movimiento del bot en un juego de ajedrez."""
    if room not in games or not games[room].get('is_bot_game'):
        logger.warning(f"Intento inválido de movimiento del bot en la sala {room}")
        return

    try:
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

        board = games[room]['board']
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
                socketio.emit('update_board', {
                    'board': board_state, 
                    'turn': games[room]['turn']
                }, room=room)

                if board.is_checkmate():
                    socketio.emit('bot_chat_message', {
                        'message': random.choice(BOT_MESSAGES['checkmate'])
                    }, room=room)
                    winner = 'black' if games[room]['turn'] == 'white' else 'white'
                    end_game(room, winner)
                elif board.is_check():
                    socketio.emit('bot_chat_message', {
                        'message': random.choice(BOT_MESSAGES['check'])
                    }, room=room)
                    socketio.emit('check', {'message': '¡Jaque!'}, room=room)
                elif board.is_stalemate() or board.is_insufficient_material() or board.is_seventyfive_moves() or board.is_fivefold_repetition():
                    socketio.emit('bot_chat_message', {
                        'message': random.choice(BOT_MESSAGES['stalemate'])
                    }, room=room)
                    socketio.emit('game_over', {'message': '¡Partida terminada en tablas!'}, room=room)
                    del players[room]
                    del games[room]
                    logger.info(f"Tablas en la sala {room}")
                else:
                    socketio.emit('bot_chat_message', {
                        'message': random.choice(BOT_MESSAGES['move'])
                    }, room=room)
        except Exception as e:
            logger.error(f"Error al ejecutar Stockfish en la sala {room}: {str(e)}")
            socketio.emit('error', {
                'message': f'Error al generar el movimiento del bot: {str(e)}'
            }, room=room)
    except Exception as e:
        logger.error(f"Error general en el movimiento del bot en la sala {room}: {str(e)}")
        socketio.emit('error', {
            'message': 'Error interno en el movimiento del bot'
        }, room=room)

@socketio.on('move')
def on_move(data):
    """Manejar un movimiento en el juego (ajedrez o damas)."""
    sid = request.sid
    try:
        from_square = data['from']
        to_square = data['to']
        promotion = data.get('promotion')
        room = data['room']
        game_type = games.get(room, {}).get('game_type', 'chess')

        if room not in games or sid not in players[room]:
            emit('error', {'message': 'Sala no encontrada o no autorizado'}, room=room)
            logger.warning(f"Intento de movimiento en sala inexistente {room} o no autorizado")
            return

        game = games[room]
        if game['turn'] != players[room][sid]['color']:
            emit('error', {'message': 'No es tu turno'}, room=room)
            logger.warning(f"Intento de movimiento fuera de turno en sala {room}")
            return

        if game_type == 'chess':
            board = game['board']
            move_uci = from_square + to_square
            if promotion:
                move_uci += promotion.lower()

            try:
                move = chess.Move.from_uci(move_uci)
            except ValueError:
                emit('error', {'message': 'Movimiento inválido'}, room=room)
                logger.warning(f"Movimiento inválido {move_uci} en la sala {room}")
                return

            if move in board.legal_moves:
                board.push(move)
                game['turn'] = 'black' if game['turn'] == 'white' else 'white'

                board_state = [['.' for _ in range(8)] for _ in range(8)]
                for square in chess.SQUARES:
                    piece = board.piece_at(square)
                    if piece:
                        row, col = 7 - (square // 8), square % 8
                        board_state[row][col] = piece.symbol()

                update_timer(room)
                socketio.emit('update_board', {
                    'board': board_state,
                    'turn': game['turn']
                }, room=room)

                if board.is_check():
                    socketio.emit('check', {'message': '¡Jaque!'}, room=room)
                if board.is_checkmate():
                    winner = 'black' if game['turn'] == 'white' else 'white'
                    end_game(room, winner)
                    logger.info(f"Jaque mate en la sala {room}, ganador: {winner}")
                elif board.is_stalemate() or board.is_insufficient_material() or board.is_seventyfive_moves() or board.is_fivefold_repetition():
                    socketio.emit('game_over', {'message': '¡Partida terminada en tablas!'}, room=room)
                    del players[room]
                    del games[room]
                    logger.info(f"Tablas en la sala {room}")
                elif game.get('is_bot_game') and game['turn'] != players[room][sid]['color']:
                    make_bot_move(room, sid)
            else:
                emit('error', {'message': 'Movimiento ilegal'}, room=room)
                logger.warning(f"Movimiento ilegal {move_uci} en la sala {room}")
        else:
            board = game['board']
            try:
                from_row = 8 - int(from_square[1])
                from_col = ord(from_square[0]) - ord('a')
                to_row = 8 - int(to_square[1])
                to_col = ord(to_square[0]) - ord('a')

                if board[from_row][from_col] == '.' or abs(to_row - from_row) != abs(to_col - from_col):
                    emit('error', {'message': 'Movimiento inválido'}, room=room)
                    logger.warning(f"Movimiento inválido de damas desde {from_square} a {to_square} en la sala {room}")
                    return

                piece = board[from_row][from_col]
                if (piece == 'w' and game['turn'] != 'white') or (piece == 'b' and game['turn'] != 'black'):
                    emit('error', {'message': 'No es tu turno'}, room=room)
                    logger.warning(f"Turno incorrecto para movimiento de damas en la sala {room}")
                    return

                if abs(to_row - from_row) == 1 and abs(to_col - from_col) == 1:
                    if board[to_row][to_col] == '.':
                        board[to_row][to_col] = board[from_row][from_col]
                        board[from_row][from_col] = '.'
                        game['turn'] = 'black' if game['turn'] == 'white' else 'white'
                    else:
                        emit('error', {'message': 'Casilla ocupada'}, room=room)
                        logger.warning(f"Casilla ocupada en movimiento de damas en la sala {room}")
                        return
                elif abs(to_row - from_row) == 2 and abs(to_col - from_col) == 2:
                    mid_row = (from_row + to_row) // 2
                    mid_col = (from_col + to_col) // 2
                    if board[mid_row][mid_col] in ('w', 'b') and board[mid_row][mid_col] != piece:
                        if board[to_row][to_col] == '.':
                            board[to_row][to_col] = board[from_row][from_col]
                            board[from_row][from_col] = '.'
                            board[mid_row][mid_col] = '.'
                            game['turn'] = 'black' if game['turn'] == 'white' else 'white'
                        else:
                            emit('error', {'message': 'Casilla ocupada'}, room=room)
                            logger.warning(f"Casilla ocupada en captura de damas en la sala {room}")
                            return
                    else:
                        emit('error', {'message': 'No hay pieza para capturar'}, room=room)
                        logger.warning(f"No hay pieza para capturar en movimiento de damas en la sala {room}")
                        return
                else:
                    emit('error', {'message': 'Movimiento inválido'}, room=room)
                    logger.warning(f"Distancia inválida en movimiento de damas en la sala {room}")
                    return

                update_timer(room)
                socketio.emit('update_board', {
                    'board': board,
                    'turn': game['turn']
                }, room=room)

                white_pieces = sum(row.count('w') for row in board)
                black_pieces = sum(row.count('b') for row in board)
                if white_pieces == 0:
                    socketio.emit('game_over', {'message': '¡Negras ganan! No hay más fichas blancas.'}, room=room)
                    end_game(room, 'black')
                    logger.info(f"Negras ganan damas en la sala {room}")
                elif black_pieces == 0:
                    socketio.emit('game_over', {'message': '¡Blancas ganan! No hay más fichas negras.'}, room=room)
                    end_game(room, 'white')
                    logger.info(f"Blancas ganan damas en la sala {room}")
            except Exception as e:
                logger.error(f"Error en la lógica de damas en la sala {room}: {str(e)}")
                emit('error', {'message': 'Error procesando el movimiento de damas'}, room=room)
    except Exception as e:
        logger.error(f"Error general al procesar movimiento en la sala {room}: {str(e)}")
        emit('error', {'message': 'Error procesando el movimiento'}, room=room)

@socketio.on('resign')
def on_resign(data):
    """Manejar el abandono de un jugador."""
    sid = request.sid
    try:
        room = data['room']
        if room not in players or sid not in players[room]:
            emit('error', {'message': 'Sala no encontrada o no autorizado'}, to=sid)
            return
        user_data = load_user_data(sessions[sid])
        elo_points = 50 if not games[room].get('is_bot_game') else (50 if games[room]['difficulty'] == 'easy' else 100 if games[room]['difficulty'] == 'medium' else 150)
        neig_points = 25 if not games[room].get('is_bot_game') else (25 if games[room]['difficulty'] == 'easy' else 50 if games[room]['difficulty'] == 'medium' else 75)
        if games[room].get('is_bot_game'):
            user_data['elo'] = max(0, user_data['elo'] - elo_points)
            user_data['neig'] = max(0, user_data['neig'] - neig_points)
            user_data['level'] = calculate_level(user_data['elo'])
            save_user_data(sessions[sid], user_data['neig'], user_data['elo'], user_data['level'])
            emit('user_data_update', {
                'neig': user_data['neig'], 
                'elo': user_data['elo'], 
                'level': user_data['level']
            }, to=sid)
            emit('resigned', {
                'message': f'Abandonaste la partida contra Stockfish. Perdiste {elo_points} ELO y {neig_points} Neig.',
                'elo': user_data['elo'],
                'neig': user_data['neig'],
                'level': user_data['level']
            }, to=sid)
            logger.info(f"Usuario {sessions[sid]} abandonó contra el bot en la sala {room}")
        else:
            winner_sid = next(s for s in players[room] if s != sid)
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
            emit('user_data_update', {
                'neig': winner_data['neig'], 
                'elo': winner_data['elo'], 
                'level': winner_data['level']
            }, to=winner_sid)
            emit('user_data_update', {
                'neig': loser_data['neig'], 
                'elo': loser_data['elo'], 
                'level': loser_data['level']
            }, to=sid)
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
            logger.info(f"Usuario {loser_username} abandonó, {winner_username} gana en la sala {room}")
        del players[room]
        del games[room]
    except Exception as e:
        logger.error(f"Error al procesar abandono en la sala {room}: {str(e)}")
        emit('error', {'message': 'Error al procesar el abandono'}, to=sid)

@socketio.on('leave')
def on_leave(data):
    """Manejar la salida de un jugador de una sala."""
    sid = request.sid
    try:
        room = data['room']
        if room in players and sid in players[room]:
            del players[room][sid]
            if not players[room]:
                del players[room]
                if room in games:
                    del games[room]
            else:
                socketio.emit('player_left', {'message': 'El oponente abandonó la partida'}, room=room)
            leave_room(room)
            logger.info(f"Usuario salió de la sala {room}")
    except Exception as e:
        logger.error(f"Error al salir de la sala {room}: {str(e)}")

@socketio.on('chat_message')
def on_chat_message(data):
    """Manejar mensajes de texto en el chat de la sala."""
    sid = request.sid
    try:
        room = data['room']
        message = data['message']
        if room in players and sid in players[room]:
            socketio.emit('new_message', {
                'color': players[room][sid]['color'], 
                'message': message
            }, room=room)
            logger.info(f"Mensaje en la sala {room}: {message}")
    except Exception as e:
        logger.error(f"Error en el mensaje de la sala {room}: {str(e)}")

@socketio.on('audio_message')
def on_audio_message(data):
    """Manejar mensajes de voz en el chat de la sala."""
    sid = request.sid
    try:
        room = data['room']
        audio = data['audio']
        if room in players and sid in players[room]:
            socketio.emit('audio_message', {
                'color': players[room][sid]['color'], 
                'audio': audio
            }, room=room)
            logger.info(f"Mensaje de voz enviado en la sala {room}")
    except Exception as e:
        logger.error(f"Error en el mensaje de voz de la sala {room}: {str(e)}")

@socketio.on('video_signal')
def on_video_signal(data):
    """Manejar señales de videollamada."""
    sid = request.sid
    try:
        room = data['room']
        signal = data['signal']
        if room in players and sid in players[room] and not games[room].get('is_bot_game'):
            socketio.emit('video_signal', {'signal': signal}, room=room, skip_sid=sid)
            logger.info(f"Señal de video enviada en la sala {room}")
    except Exception as e:
        logger.error(f"Error en la señal de video para la sala {room}: {str(e)}")

@socketio.on('video_stop')
def on_video_stop(data):
    """Detener la videollamada."""
    try:
        room = data['room']
        if room in players and not games[room].get('is_bot_game'):
            socketio.emit('video_stop', {}, room=room)
            logger.info(f"Video detenido en la sala {room}")
    except Exception as e:
        logger.error(f"Error al detener el video en la sala {room}: {str(e)}")

@socketio.on('save_game')
def on_save_game(data):
    """Guardar una partida."""
    sid = request.sid
    try:
        room = data['room']
        game_name = data['game_name']
        game_type = games.get(room, {}).get('game_type', 'chess')
        username = sessions.get(sid)
        if not username:
            emit('error', {'message': 'Debes iniciar sesión'}, to=sid)
            logger.warning(f"Intento no autorizado de guardar partida desde SID {sid}")
            return
        if room not in games:
            emit('error', {'message': 'Sala no encontrada'}, to=sid)
            logger.warning(f"Intento de guardar partida en sala inexistente {room}")
            return
        conn = sqlite3.connect(DATABASE_PATH)
        c = conn.cursor()
        if game_type == 'chess':
            fen = games[room]['board'].fen()
        else:
            fen = board_to_fen(games[room]['board'], games[room]['turn'], game_type)
        c.execute('INSERT INTO saved_games (username, room, game_name, fen, turn, game_type) VALUES (?, ?, ?, ?, ?, ?)',
                  (username, room, game_name, fen, games[room]['turn'], game_type))
        conn.commit()
        emit('game_saved', {'message': f'Partida "{game_name}" guardada exitosamente'})
        logger.info(f"Partida {game_name} guardada por {username} en la sala {room}")
    except Exception as e:
        logger.error(f"Error al guardar partida en la sala {room}: {str(e)}")
        emit('error', {'message': 'Error al guardar la partida'}, to=sid)
    finally:
        conn.close()

@socketio.on('get_saved_games')
def on_get_saved_games(data):
    """Obtener las partidas guardadas de un usuario."""
    sid = request.sid
    try:
        username = data['username']
        if not username or username != sessions.get(sid):
            emit('error', {'message': 'No autorizado'}, to=sid)
            logger.warning(f"Intento no autorizado de obtener partidas guardadas desde SID {sid}")
            return
        conn = sqlite3.connect(DATABASE_PATH)
        c = conn.cursor()
        c.execute('SELECT room, game_name, fen, turn, game_type FROM saved_games WHERE username = ?', (username,))
        games_list = [{'room': row[0], 'game_name': row[1], 'fen': row[2], 'turn': row[3], 'game_type': row[4]} for row in c.fetchall()]
        emit('saved_games_list', {'games': games_list}, to=sid)
        logger.info(f"Partidas guardadas recuperadas para {username}")
    except Exception as e:
        logger.error(f"Error al recuperar partidas guardadas para {username}: {str(e)}")
        emit('error', {'message': 'Error al obtener partidas guardadas'}, to=sid)
    finally:
        conn.close()

@socketio.on('load_game')
def on_load_game(data):
    """Cargar una partida guardada."""
    sid = request.sid
    try:
        username = data['username']
        game_name = data['game_name']
        if not username or username != sessions.get(sid):
            emit('error', {'message': 'No autorizado'}, to=sid)
            logger.warning(f"Intento no autorizado de cargar partida desde SID {sid}")
            return
        conn = sqlite3.connect(DATABASE_PATH)
        c = conn.cursor()
        c.execute('SELECT room, fen, turn, game_type FROM saved_games WHERE username = ? AND game_name = ?', 
                  (username, game_name))
        result = c.fetchone()
        if result:
            room, fen, turn, game_type = result
            if game_type == 'chess':
                board = chess.Board(fen)
                board_state = [['.' for _ in range(8)] for _ in range(8)]
                for square in chess.SQUARES:
                    piece = board.piece_at(square)
                    if piece:
                        row, col = 7 - (square // 8), square % 8
                        board_state[row][col] = piece.symbol()
            else:
                board = json.loads(fen)
                board_state = board

            games[room] = {
                'board': board,
                'turn': turn,
                'time_white': None,
                'time_black': None,
                'game_type': game_type
            }
            players[room] = {sid: {'color': 'white', 'chosen_color': '#FFFFFF', 'username': username}}
            join_room(room)
            emit('game_loaded', {
                'room': room,
                'board': board_state,
                'turn': turn,
                'game_name': game_name,
                'game_type': game_type
            }, to=sid)
            logger.info(f"Partida {game_name} cargada por {username} en la sala {room}")
        else:
            emit('error', {'message': 'Partida no encontrada'}, to=sid)
            logger.warning(f"Partida {game_name} no encontrada para {username}")
    except Exception as e:
        logger.error(f"Error al cargar partida {game_name} para {username}: {str(e)}")
        emit('error', {'message': 'Error al cargar la partida'}, to=sid)
    finally:
        conn.close()

@socketio.on('join_waitlist')
def on_join_waitlist(data):
    """Unirse a la lista de espera para un juego."""
    sid = request.sid
    try:
        username = sessions.get(sid)
        chosen_color = data.get('color', '#FFFFFF')
        avatar = data.get('avatar', '/static/default-avatar.png')
        game_type = data.get('game_type', 'chess')
        if username and sid not in available_players:
            available_players[sid] = {
                'username': username, 
                'chosen_color': chosen_color, 
                'avatar': avatar, 
                'game_type': game_type
            }
            socketio.emit('waitlist_update', {
                'players': [{'sid': s, 'username': info['username'], 'chosen_color': info['chosen_color'], 'avatar': info['avatar'], 'game_type': info['game_type']} for s, info in available_players.items()]
            })
            logger.info(f"Usuario {username} se unió a la lista de espera para {game_type}")
    except Exception as e:
        logger.error(f"Error al unirse a la lista de espera para SID {sid}: {str(e)}")

@socketio.on('leave_waitlist')
def on_leave_waitlist():
    """Salir de la lista de espera."""
    sid = request.sid
    try:
        if sid in available_players:
            username = available_players[sid]['username']
            del available_players[sid]
            socketio.emit('waitlist_update', {
                'players': [{'sid': s, 'username': info['username'], 'chosen_color': info['chosen_color'], 'avatar': info['avatar'], 'game_type': info['game_type']} for s, info in available_players.items()]
            })
            logger.info(f"Usuario {username} salió de la lista de espera")
    except Exception as e:
        logger.error(f"Error al salir de la lista de espera para SID {sid}: {str(e)}")

@socketio.on('select_opponent')
def on_select_opponent(data):
    """Seleccionar un oponente de la lista de espera."""
    sid = request.sid
    try:
        opponent_sid = data['opponent_sid']
        if opponent_sid in available_players and sid in available_players:
            room = f"private_{sid}_{opponent_sid}"
            username = sessions[sid]
            opponent_username = available_players[opponent_sid]['username']
            game_type = available_players[sid]['game_type']
            join_room(room, sid)
            join_room(room, opponent_sid)
            emit('private_chat_start', {
                'room': room, 
                'opponent': opponent_username, 
                'game_type': game_type
            }, to=sid)
            emit('private_chat_start', {
                'room': room, 
                'opponent': username, 
                'game_type': game_type
            }, to=opponent_sid)
            del available_players[sid]
            del available_players[opponent_sid]
            socketio.emit('waitlist_update', {
                'players': [{'sid': s, 'username': info['username'], 'chosen_color': info['chosen_color'], 'avatar': info['avatar'], 'game_type': info['game_type']} for s, info in available_players.items()]
            })
            logger.info(f"Chat privado iniciado entre {username} y {opponent_username} en la sala {room}")
    except Exception as e:
        logger.error(f"Error al seleccionar oponente para SID {sid}: {str(e)}")

@socketio.on('private_message')
def on_private_message(data):
    """Manejar mensajes privados."""
    sid = request.sid
    try:
        room = data['room']
        message = data['message']
        username = sessions.get(sid)
        socketio.emit('private_message', {
            'username': username, 
            'message': message
        }, room=room)
        logger.info(f"Mensaje privado de {username} en la sala {room}: {message}")
    except Exception as e:
        logger.error(f"Error en el mensaje privado para la sala {room}: {str(e)}")

@socketio.on('accept_conditions')
def on_accept_conditions(data):
    """Aceptar condiciones para iniciar un juego."""
    sid = request.sid
    try:
        room = data['room']
        username = sessions.get(sid)
        game_type = games.get(room, {}).get('game_type', 'chess')
        if room not in players:
            players[room] = {}
        players[room][sid] = {
            'color': 'white' if len(players[room]) == 0 else 'black', 
            'chosen_color': '#FFFFFF', 
            'username': username
        }
        if len(players[room]) == 2:
            if game_type == 'chess':
                board = reset_chess_board()
                board_state = [['.' for _ in range(8)] for _ in range(8)]
                for square in chess.SQUARES:
                    piece = board.piece_at(square)
                    if piece:
                        row, col = 7 - (square // 8), square % 8
                        board_state[row][col] = piece.symbol()
            else:
                board = initialize_checkers_board()
                board_state = board
            games[room] = {
                'board': board,
                'turn': 'white',
                'time_white': None,
                'time_black': None,
                'game_type': game_type
            }
            player_colors = {players[room][s]['color']: players[room][s]['chosen_color'] for s in players[room]}
            socketio.emit('game_start', {
                'board': board_state,
                'turn': 'white',
                'time_white': None,
                'time_black': None,
                'playerColors': player_colors,
                'room': room,
                'game_type': game_type
            }, room=room)
            logger.info(f"Juego iniciado tras aceptar condiciones en la sala {room} para {game_type}")
    except Exception as e:
        logger.error(f"Error al aceptar condiciones en la sala {room}: {str(e)}")

@socketio.on('leave_private_chat')
def on_leave_private_chat(data):
    """Salir de un chat privado."""
    sid = request.sid
    try:
        room = data['room']
        leave_room(room)
        if room in players:
            del players[room]
        if room in games:
            del games[room]
        logger.info(f"Usuario salió del chat privado en la sala {room}")
    except Exception as e:
        logger.error(f"Error al salir del chat privado en la sala {room}: {str(e)}")

if __name__ == '__main__':
    try:
        logger.info("Iniciando servidor Flask-SocketIO")
        socketio.run(app, host='0.0.0.0', port=int(os.getenv('PORT', 10000)))
    except Exception as e:
        logger.error(f"Error al iniciar el servidor: {str(e)}")
        raise
