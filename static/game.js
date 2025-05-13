let room = null;
let board = null;
let turn = null;
let selectedSquare = null;
let timeWhite = null;
let timeBlack = null;
let lastUpdateTime = null;
let timerInterval = null;
let mediaRecorder = null;
let audioChunks = [];
let previousBoard = null;
let peer = null;
let localStream = null;
let playerColors = {};
let myColor = null;
let neigBalance = 10000;
let eloPoints = 0;
let level = 0;
let username = null;
let currentAvatar = null;
let isBotGame = false;

const socket = io(location.hostname === 'localhost' ? 'http://localhost:10000' : 'https://peonkingame.onrender.com');
const chessboard = document.getElementById('chessboard');
const roomSelection = document.getElementById('room-selection');
const chat = document.getElementById('chat');
const gameButtons = document.getElementById('game-buttons');
const savedGamesDiv = document.getElementById('saved-games');
const timers = document.getElementById('timers');

function joinRoom() {
    room = document.getElementById('room-id').value.trim();
    const timer = document.getElementById('timer-select').value;
    const color = document.getElementById('color-select').value;

    if (!room) {
        console.log('Error: ID de sala vacío');
        return alert('Por favor, ingresá un ID de sala.');
    }

    console.log(`Intentando unirse a la sala: ${room}`);
    socket.emit('join', { room, timer, color });
}

function playWithBot() {
    if (!username) {
        console.error('No hay usuario logueado');
        alert('Por favor, iniciá sesión primero.');
        return;
    }
    const timer = document.getElementById('timer-select').value;
    const color = document.getElementById('color-select').value;
    socket.emit('play_with_bot', { timer, color });
}

function watchGame(room) {
    socket.emit('watch_game', { room });
}

function renderOnlinePlayers(players) {
    const onlineDiv = document.getElementById('online-players');
    onlineDiv.innerHTML = '<h3>Jugadores en Línea</h3>';
    players.forEach(player => {
        const p = document.createElement('p');
        const img = document.createElement('img');
        img.src = player.avatar || '/static/default-avatar.png';
        img.style.width = '20px';
        img.style.height = '20px';
        img.style.marginRight = '5px';
        img.onerror = () => img.src = '/static/default-avatar.png';
        p.appendChild(img);
        p.appendChild(document.createTextNode(player.username));
        onlineDiv.appendChild(p);
    });
}

function sendGlobalMessage() {
    const input = document.getElementById('global-chat-input');
    const message = input.value.trim();
    if (message) {
        socket.emit('global_message', { message });
        input.value = '';
    }
}

function joinWaitlist() {
    if (!username) {
        console.error('No hay usuario logueado');
        alert('Por favor, iniciá sesión primero.');
        return;
    }
    const color = document.getElementById('color-select').value;
    socket.emit('join_waitlist', { color, avatar: currentAvatar });
    document.getElementById('room-selection').style.display = 'none';
    document.getElementById('waitlist').style.display = 'block';
    document.querySelector('.container').style.display = 'none';
}

function goBackFromWaitlist() {
    socket.emit('leave_waitlist');
    document.getElementById('waitlist').style.display = 'none';
    document.querySelector('.container').style.display = 'flex';
    document.getElementById('room-selection').style.display = 'block';
}

function goBackFromPrivateChat() {
    socket.emit('leave_private_chat', { room });
    document.getElementById('private-chat').style.display = 'none';
    document.querySelector('.container').style.display = 'flex';
    document.getElementById('room-selection').style.display = 'block';
    room = null;
}

function renderBoard() {
    chessboard.innerHTML = '';
    const pieceSymbols = {
        'r': '♜', 'n': '♞', 'b': '♝', 'q': '♛', 'k': '♚', 'p': '♟',
        'R': '♖', 'N': '♘', 'B': '♗', 'Q': '♕', 'K': '♔', 'P': '♙'
    };
    for (let row = 0; row < 8; row++) {
        for (let col = 0; col < 8; col++) {
            const square = document.createElement('div');
            square.className = 'square ' + ((row + col) % 2 === 0 ? 'white' : 'black');
            square.dataset.row = row;
            square.dataset.col = col;
            const piece = board[row][col];
            square.textContent = piece === '.' ? '' : (pieceSymbols[piece] || piece);
            if (piece !== '.') square.style.color = isWhite(piece) ? playerColors['white'] : playerColors['black'];
            square.addEventListener('click', handleSquareClick);
            chessboard.appendChild(square);
        }
    }
}

function handleSquareClick(event) {
    const square = event.target.closest('.square');
    if (!square) return;
    const row = parseInt(square.dataset.row);
    const col = parseInt(square.dataset.col);
    if (!room && !isBotGame) {
        console.log('Error: No estás en una sala');
        alert('No estás en una sala');
        return;
    }
    if (myColor !== turn) {
        console.log(`No es tu turno. Turno actual: ${turn}, Tu color: ${myColor}`);
        alert('No es tu turno');
        return;
    }
    const piece = board[row][col];
    const position = String.fromCharCode(97 + col) + (8 - row); // Ej., "e4"
    if (!selectedSquare) {
        if (piece !== '.' && ((myColor === 'white' && isWhite(piece)) || (myColor === 'black' && !isWhite(piece)))) {
            selectedSquare = square;
            square.classList.add('selected');
        }
    } else {
        const from = String.fromCharCode(97 + parseInt(selectedSquare.dataset.col)) + (8 - parseInt(selectedSquare.dataset.row));
        const to = position;
        socket.emit('move', { from, to, room });
        selectedSquare.classList.remove('selected');
        selectedSquare = null;
    }
}

function isWhite(piece) {
    return piece === piece.toUpperCase();
}

function formatTime(seconds) {
    if (seconds === null || isNaN(seconds) || seconds < 0) return '--:--.--';
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    const millis = Math.floor((seconds % 1) * 100);
    return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}.${millis.toString().padStart(2, '0')}`;
}

function updateTimers() {
    document.getElementById('white-timer').textContent = `Blancas: ${formatTime(timeWhite)}`;
    document.getElementById('black-timer').textContent = `Negras: ${formatTime(timeBlack)}`;
}

function startTimer() {
    if (timerInterval) clearInterval(timerInterval);
    lastUpdateTime = Date.now();
    timerInterval = setInterval(() => {
        if (timeWhite !== null && timeBlack !== null) {
            const now = Date.now();
            const elapsed = (now - lastUpdateTime) / 1000;
            lastUpdateTime = now;
            if (turn === 'white') timeWhite = Math.max(0, timeWhite - elapsed);
            else timeBlack = Math.max(0, timeBlack - elapsed);
            updateTimers();
        }
    }, 10);
}

function stopTimer() {
    if (timerInterval) {
        clearInterval(timerInterval);
        timerInterval = null;
    }
}

function goBack() {
    socket.emit('leave', { room });
    roomSelection.style.display = 'block';
    document.querySelector('.container').style.display = 'flex';
    chessboard.style.display = 'none';
    chat.style.display = 'none';
    gameButtons.style.display = 'none';
    timers.style.display = 'none';
    savedGamesDiv.style.display = 'none';
    stopTimer();
    room = null;
    board = null;
    turn = null;
    selectedSquare = null;
    timeWhite = null;
    timeBlack = null;
    myColor = null;
    updateTimers();
}

function sendMessage() {
    const input = document.getElementById('chat-input');
    const message = input.value.trim();
    if (message && room) {
        socket.emit('chat_message', { room, message });
        input.value = '';
    }
}

function startRecording() {
    navigator.mediaDevices.getUserMedia({ audio: true })
        .then(stream => {
            mediaRecorder = new MediaRecorder(stream);
            audioChunks = [];
            mediaRecorder.ondataavailable = event => audioChunks.push(event.data);
            mediaRecorder.onstop = () => {
                const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
                sendAudioMessage(audioBlob);
                stream.getTracks().forEach(track => track.stop());
            };
            mediaRecorder.start();
            document.getElementById('record-audio').style.display = 'none';
            document.getElementById('stop-audio').style.display = 'inline';
        });
}

function stopRecording() {
    if (mediaRecorder && mediaRecorder.state !== 'inactive') {
        mediaRecorder.stop();
        document.getElementById('record-audio').style.display = 'inline';
        document.getElementById('stop-audio').style.display = 'none';
    }
}

function sendAudioMessage(audioBlob) {
    if (room) {
        const reader = new FileReader();
        reader.onload = () => {
            const audioData = reader.result.split(',')[1];
            socket.emit('audio_message', { room, audio: audioData });
        };
        reader.readAsDataURL(audioBlob);
    }
}

function startVideoCall() {
    navigator.mediaDevices.getUserMedia({ video: true, audio: true })
        .then(stream => {
            localStream = stream;
            document.getElementById('local-video').srcObject = stream;
            document.getElementById('local-video').style.display = 'block';
            document.getElementById('start-video').style.display = 'none';
            document.getElementById('stop-video').style.display = 'inline';
            peer = new SimplePeer({ initiator: !room.includes('bot'), stream });
            peer.on('signal', data => socket.emit('video_signal', { room, signal: data }));
            peer.on('stream', remoteStream => {
                document.getElementById('remote-video').srcObject = remoteStream;
                document.getElementById('remote-video').style.display = 'block';
            });
        });
}

function stopVideoCall() {
    if (localStream) {
        localStream.getTracks().forEach(track => track.stop());
        document.getElementById('local-video').srcObject = null;
        document.getElementById('remote-video').srcObject = null;
        document.getElementById('local-video').style.display = 'none';
        document.getElementById('remote-video').style.display = 'none';
        document.getElementById('start-video').style.display = 'inline';
        document.getElementById('stop-video').style.display = 'none';
    }
    if (peer) {
        peer.destroy();
        peer = null;
    }
    socket.emit('video_stop', { room });
}

function updateUserData(data) {
    neigBalance = data.neig;
    eloPoints = data.elo;
    level = data.level;
    document.getElementById('neig-balance').textContent = `${neigBalance} Neig`;
    document.getElementById('elo-level').textContent = `ELO: ${eloPoints} (Nivel ${level})`;
}

function saveGame() {
    if (!username) return alert('Debes iniciar sesión para guardar una partida');
    const gameName = prompt('Ingresá un nombre para la partida:');
    if (gameName && room) {
        socket.emit('save_game', { room, game_name: gameName, board, turn });
    }
}

function resignGame() {
    if (room) {
        socket.emit('resign', { room });
    }
}

function loadSavedGames() {
    if (!username) return alert('Debes iniciar sesión para cargar una partida');
    socket.emit('get_saved_games', { username });
    savedGamesDiv.style.display = 'block';
}

function loadGame(gameName) {
    if (!username) return alert('Debes iniciar sesión para cargar una partida');
    socket.emit('load_game', { username, game_name: gameName });
}

function selectOpponent(opponentSid) {
    socket.emit('select_opponent', { opponent_sid: opponentSid });
}

function sendPrivateMessage() {
    const input = document.getElementById('private-chat-input');
    const message = input.value.trim();
    if (message && room) {
        socket.emit('private_message', { room, message });
        input.value = '';
    }
}

function acceptConditions() {
    socket.emit('accept_conditions', { room });
}

function login(usernameInput, password) {
    socket.emit('login', { username: usernameInput, password });
}

function logout() {
    if (!username) return;
    socket.emit('logout', { username });
    username = null;
    currentAvatar = null;
    neigBalance = 10000;
    eloPoints = 0;
    level = 0;
    document.getElementById('login-register').style.display = 'block';
    document.querySelector('.container').style.display = 'none';
    document.getElementById('room-selection').style.display = 'none';
    document.getElementById('waitlist').style.display = 'none';
    document.getElementById('private-chat').style.display = 'none';
    document.getElementById('neig-balance').textContent = '10000 Neig';
    document.getElementById('elo-level').textContent = 'ELO: 0 (Nivel 0)';
    goBack();
    stopVideoCall();
    socket.disconnect();
    socket.connect();
}

function handleTouchStart(event) {
    event.preventDefault();
    const square = event.target.closest('.square');
    if (!square) return;
    selectedSquare = square;
    square.classList.add('selected');
}

function handleTouchEnd(event) {
    event.preventDefault();
    if (!selectedSquare) return;
    const touchEndPos = { x: event.changedTouches[0].clientX, y: event.changedTouches[0].clientY };
    const square = document.elementFromPoint(touchEndPos.x, touchEndPos.y);
    if (square && square.classList.contains('square') && square !== selectedSquare) {
        const from = String.fromCharCode(97 + parseInt(selectedSquare.dataset.col)) + (8 - parseInt(selectedSquare.dataset.row));
        const to = String.fromCharCode(97 + parseInt(square.dataset.col)) + (8 - parseInt(square.dataset.row));
        socket.emit('move', { from, to, room });
    }
    selectedSquare.classList.remove('selected');
    selectedSquare = null;
}

const chessboard = document.getElementById('chessboard');
chessboard.addEventListener('touchstart', handleTouchStart);
chessboard.addEventListener('touchend', handleTouchEnd);

function register() {
    const formData = new FormData(document.getElementById('register-form'));
    fetch('/register', { method: 'POST', body: formData })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                username = data.username;
                currentAvatar = data.avatar;
                document.getElementById('login-register').style.display = 'none';
                document.querySelector('.container').style.display = 'flex';
                document.getElementById('room-selection').style.display = 'block';
                socket.emit('join_user_room', { username });
                socket.emit('get_user_data', { username });
            } else {
                document.getElementById('register-error').textContent = data.error;
            }
        });
}

function previewAvatar(event) {
    const file = event.target.files[0];
    if (file) {
        const reader = new FileReader();
        reader.onload = function(e) {
            document.getElementById('avatar-preview').src = e.target.result;
        };
        reader.readAsDataURL(file);
    }
}

socket.on('connect', () => {
    if (username) {
        socket.emit('join_user_room', { username });
        socket.emit('get_user_data', { username });
    }
});

socket.on('online_players_update', players => {
    renderOnlinePlayers(players);
});

socket.on('global_message', data => {
    const globalChat = document.getElementById('global-chat');
    const msg = document.createElement('div');
    msg.textContent = `${data.username}: ${data.message}`;
    globalChat.appendChild(msg);
    globalChat.scrollTop = globalChat.scrollHeight;
});

socket.on('color_assigned', data => {
    myColor = data.color;
    playerColors[data.color] = data.chosenColor;
});

socket.on('game_start', data => {
    room = data.room; // Asignar el ID de la sala
    isBotGame = data.is_bot_game || false; // Indicar si es partida con bot
    board = data.board;
    turn = data.turn;
    timeWhite = data.time_white;
    timeBlack = data.time_black;
    playerColors = data.playerColors || data.players;
    previousBoard = JSON.parse(JSON.stringify(board));
    roomSelection.style.display = 'none';
    chessboard.style.display = 'grid';
    chat.style.display = 'block';
    gameButtons.style.display = 'block';
    timers.style.display = 'block';
    savedGamesDiv.style.display = 'none';
    document.querySelector('.container').style.display = 'flex';
    renderBoard();
    updateTimers();
    if (timeWhite !== null && timeBlack !== null) startTimer();
    console.log('Partida iniciada en sala:', room);
});

socket.on('update_board', data => {
    board = data.board;
    turn = data.turn;
    previousBoard = JSON.parse(JSON.stringify(board));
    renderBoard();
});

socket.on('timer_update', data => {
    timeWhite = data.time_white;
    timeBlack = data.time_black;
    lastUpdateTime = Date.now();
    updateTimers();
});

socket.on('new_message', data => {
    const messages = document.getElementById('chat-messages');
    const message = document.createElement('div');
    message.textContent = `${data.color}: ${data.message}`;
    messages.appendChild(message);
    messages.scrollTop = messages.scrollHeight;
});

socket.on('audio_message', data => {
    const messages = document.getElementById('chat-messages');
    const messageDiv = document.createElement('div');
    if (data.color) messageDiv.textContent = `${data.color}: `;
    const audio = document.createElement('audio');
    audio.controls = true;
    audio.src = `data:audio/webm;base64,${data.audio}`;
    messageDiv.appendChild(audio);
    messages.appendChild(messageDiv);
    messages.scrollTop = messages.scrollHeight;
});

socket.on('video_signal', data => {
    if (!peer) {
        navigator.mediaDevices.getUserMedia({ video: true, audio: true })
            .then(stream => {
                localStream = stream;
                document.getElementById('local-video').srcObject = stream;
                document.getElementById('local-video').style.display = 'block';
                document.getElementById('start-video').style.display = 'none';
                document.getElementById('stop-video').style.display = 'inline';
                peer = new SimplePeer({ stream });
                peer.on('signal', signal => socket.emit('video_signal', { room, signal }));
                peer.on('stream', remoteStream => {
                    document.getElementById('remote-video').srcObject = remoteStream;
                    document.getElementById('remote-video').style.display = 'block';
                });
                peer.signal(data.signal);
            });
    } else {
        peer.signal(data.signal);
    }
});

socket.on('video_stop', () => stopVideoCall());

socket.on('player_left', data => {
    alert(data.message);
    goBack();
});

socket.on('game_over', data => {
    alert(`${data.message} Ganaste ${data.elo_points || 0} ELO y ${data.neig_points || 0} Neig.`);
    updateUserData({ neig: neigBalance, elo: eloPoints, level: level });
    goBack();
});

socket.on('check', data => alert(data.message));

socket.on('resigned', data => {
    alert(data.message);
    updateUserData({ neig: data.neig, elo: data.elo, level: data.level });
    goBack();
});

socket.on('error', data => {
    console.log('Error recibido:', data.message);
    alert(data.message);
});

socket.on('game_saved', data => alert(data.message));

socket.on('saved_games_list', data => {
    savedGamesDiv.innerHTML = '';
    data.games.forEach(game => {
        const button = document.createElement('button');
        button.textContent = `${game.game_name} (Sala: ${game.room})`;
        button.onclick = () => loadGame(game.game_name);
        savedGamesDiv.appendChild(button);
    });
});

socket.on('game_loaded', data => {
    board = data.board;
    turn = data.turn;
    room = data.room;
    timeWhite = null;
    timeBlack = null;
    roomSelection.style.display = 'none';
    chessboard.style.display = 'grid';
    chat.style.display = 'block';
    gameButtons.style.display = 'block';
    timers.style.display = 'block';
    savedGamesDiv.style.display = 'none';
    document.querySelector('.container').style.display = 'flex';
    renderBoard();
    updateTimers();
    alert(`Partida "${data.game_name}" cargada exitosamente en la sala ${room}`);
});

socket.on('user_data_update', data => {
    updateUserData(data);
});

socket.on('waiting_opponent', data => alert(data.message));

socket.on('waitlist_update', data => {
    const waitlistDiv = document.getElementById('waitlist-players');
    waitlistDiv.innerHTML = '';
    if (data.players && data.players.length > 0) {
        data.players.forEach(player => {
            if (player.username !== username) {
                const div = document.createElement('div');
                div.className = 'player-item';
                const img = document.createElement('img');
                img.src = player.avatar || '/static/default-avatar.png';
                img.onerror = () => img.src = '/static/default-avatar.png';
                const span = document.createElement('span');
                span.textContent = `${player.username} (${player.chosen_color})`;
                div.appendChild(img);
                div.appendChild(span);
                div.onclick = () => selectOpponent(player.sid);
                waitlistDiv.appendChild(div);
            }
        });
    } else {
        waitlistDiv.innerHTML = '<p>No hay jugadores disponibles.</p>';
    }
});

socket.on('private_chat_start', data => {
    room = data.room;
    document.getElementById('waitlist').style.display = 'none';
    document.getElementById('private-chat').style.display = 'block';
    document.querySelector('.container').style.display = 'none';
    document.getElementById('private-chat-messages').innerHTML = `<p>Conectado con ${data.opponent}</p>`;
});

socket.on('private_message', data => {
    const messages = document.getElementById('private-chat-messages');
    const message = document.createElement('div');
    message.textContent = `${data.username}: ${data.message}`;
    messages.appendChild(message);
    messages.scrollTop = messages.scrollHeight;
});

socket.on('login_success', data => {
    username = data.username;
    currentAvatar = data.avatar;
    neigBalance = data.neig;
    eloPoints = data.elo;
    level = data.level;
    updateUserData({ neig: neigBalance, elo: eloPoints, level: level });
    document.getElementById('login-register').style.display = 'none';
    document.querySelector('.container').style.display = 'flex';
    document.getElementById('room-selection').style.display = 'block';
    socket.emit('join_user_room', { username });
});

socket.on('login_error', data => {
    document.getElementById('login-error').textContent = data.error;
});

document.getElementById('login-form')?.addEventListener('submit', e => {
    e.preventDefault();
    const formData = new FormData(e.target);
    const usernameInput = formData.get('username');
    const password = formData.get('password');
    login(usernameInput, password);
});

document.getElementById('register-form')?.addEventListener('submit', e => {
    e.preventDefault();
    register();
});

document.addEventListener('DOMContentLoaded', () => {
    if (username) socket.emit('get_user_data', { username });
});

window.onload = () => {
    setTimeout(() => {
        document.getElementById('loading-screen').style.display = 'none';
        document.getElementById('login-register').style.display = 'block';
        document.querySelector('.container').style.display = 'none';
        currentAvatar = '/static/default-avatar.png';
    }, 3000);
};
