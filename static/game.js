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
let gameType = 'chess';

const socket = io(location.hostname === 'localhost' ? 'http://localhost:10000' : 'https://peonkingame.onrender.com');
const chessboard = document.getElementById('chessboard');
const checkersboard = document.getElementById('checkersboard');
const roomSelection = document.getElementById('room-selection');
const chat = document.getElementById('chat');
const gameButtons = document.getElementById('game-buttons');
const savedGamesDiv = document.getElementById('saved-games');
const timers = document.getElementById('timers');
const promotionModal = document.getElementById('promotion-modal');

function initializeBoard(isCheckers) {
    const targetBoard = isCheckers ? checkersboard : chessboard;
    targetBoard.innerHTML = '';
    for (let i = 0; i < 8; i++) {
        for (let j = 0; j < 8; j++) {
            const square = document.createElement('div');
            square.className = `square ${(i + j) % 2 === 0 ? 'white' : 'black'}`;
            square.dataset.row = i;
            square.dataset.col = j;
            if (isCheckers && (i + j) % 2 === 1) {
                square.addEventListener('click', handleSquareClick);
                square.addEventListener('touchstart', handleTouchStart, { passive: true });
                square.addEventListener('touchend', handleTouchEnd, { passive: true });
            } else if (!isCheckers) {
                square.addEventListener('click', handleSquareClick);
                square.addEventListener('touchstart', handleTouchStart, { passive: true });
                square.addEventListener('touchend', handleTouchEnd, { passive: true });
            }
            targetBoard.appendChild(square);
        }
    }
}

function renderBoard() {
    if (!board) {
        console.log('Tablero no inicializado');
        return;
    }
    const pieceSymbols = gameType === 'chess' ? {
        'r': '♜', 'n': '♞', 'b': '♝', 'q': '♛', 'k': '♚', 'p': '♟',
        'R': '♖', 'N': '♘', 'B': '♗', 'Q': '♕', 'K': '♔', 'P': '♙'
    } : {
        'r': '🔴', 'R': '👑🔴', 'b': '⚫', 'B': '👑⚫'
    };
    const targetBoard = gameType === 'checkers' ? checkersboard : chessboard;
    const squares = targetBoard.querySelectorAll('.square');
    squares.forEach(square => {
        const row = parseInt(square.dataset.row);
        const col = parseInt(square.dataset.col);
        const piece = board[row][col] === '.' ? null : board[row][col];
        square.textContent = piece ? pieceSymbols[piece] || piece : '';
        square.classList.remove('selected');
        if (piece && piece !== '.') {
            square.style.color = gameType === 'chess' ?
                (isWhite(piece) ? playerColors['white'] || '#FFFFFF' : playerColors['black'] || '#000000') :
                (piece.toLowerCase() === 'r' ? playerColors['white'] || '#FF0000' : playerColors['black'] || '#000000');
        }
    });
    if (selectedSquare) {
        selectedSquare.classList.add('selected');
    }
}

function isWhite(piece) {
    return gameType === 'chess' ? piece === piece.toUpperCase() : piece.toLowerCase() === 'r';
}

function getLegalMoves(row, col) {
    if (gameType !== 'checkers' || !board) return [];
    const piece = board[row][col];
    if (!piece || (myColor === 'white' && !isWhite(piece)) || (myColor === 'black' && isWhite(piece))) return [];
    const isKing = piece === 'R' || piece === 'B';
    const directions = isKing ? [
        [-1, -1], [-1, 1], [1, -1], [1, 1]
    ] : (myColor === 'white' ? [
        [-1, -1], [-1, 1]
    ] : [
        [1, -1], [1, 1]
    ]);
    let moves = [];
    let captures = [];
    
    for (const [dr, dc] of directions) {
        const r1 = row + dr;
        const c1 = col + dc;
        if (r1 >= 0 && r1 < 8 && c1 >= 0 && c1 < 8 && board[r1][c1] === '.') {
            moves.push({ from: { row, col }, to: { row: r1, col: c1 }, capture: false });
        }
        const r2 = row + 2 * dr;
        const c2 = col + 2 * dc;
        if (r2 >= 0 && r2 < 8 && c2 >= 0 && c2 < 8 && board[r2][c2] === '.' &&
            board[r1][c1] !== '.' && isWhite(board[r1][c1]) !== isWhite(piece)) {
            captures.push({ from: { row, col }, to: { row: r2, col: c2 }, capture: true, captured: { row: r1, col: c1 } });
        }
    }
    
    return captures.length > 0 ? captures : moves;
}

function hasCaptures() {
    if (gameType !== 'checkers') return false;
    for (let row = 0; row < 8; row++) {
        for (let col = 0; col < 8; col++) {
            if (board[row][col] !== '.' && ((myColor === 'white' && isWhite(board[row][col])) || (myColor === 'black' && !isWhite(board[row][col])))) {
                const moves = getLegalMoves(row, col);
                if (moves.some(move => move.capture)) return true;
            }
        }
    }
    return false;
}

function handleSquareClick(event) {
    if (!username) {
        alert('Por favor, iniciá sesión primero.');
        return;
    }
    if (!room && !isBotGame) {
        alert('No estás en una sala.');
        return;
    }
    if (myColor !== turn) {
        alert('No es tu turno.');
        return;
    }
    if (!board) {
        console.log('Tablero no inicializado en handleSquareClick');
        return;
    }
    const square = event.target.closest('.square');
    if (!square) return;
    const row = parseInt(square.dataset.row);
    const col = parseInt(square.dataset.col);
    const piece = board[row][col];
    const position = String.fromCharCode(97 + col) + (8 - row);

    if (gameType === 'checkers') {
        if (!selectedSquare) {
            if (piece !== '.' && ((myColor === 'white' && isWhite(piece)) || (myColor === 'black' && !isWhite(piece)))) {
                const moves = getLegalMoves(row, col);
                if (moves.length > 0) {
                    selectedSquare = square;
                    square.classList.add('selected');
                }
            }
        } else {
            const fromRow = parseInt(selectedSquare.dataset.row);
            const fromCol = parseInt(selectedSquare.dataset.col);
            const from = String.fromCharCode(97 + fromCol) + (8 - fromRow);
            const to = position;
            const moves = getLegalMoves(fromRow, fromCol);
            const move = moves.find(m => m.to.row === row && m.to.col === col);
            if (move) {
                socket.emit('move', { from, to, room });
            }
            selectedSquare.classList.remove('selected');
            selectedSquare = null;
        }
    } else {
        if (!selectedSquare) {
            if (piece !== '.' && ((myColor === 'white' && isWhite(piece)) || (myColor === 'black' && !isWhite(piece)))) {
                selectedSquare = square;
                square.classList.add('selected');
            }
        } else {
            const fromRow = parseInt(selectedSquare.dataset.row);
            const fromCol = parseInt(selectedSquare.dataset.col);
            const from = String.fromCharCode(97 + fromCol) + (8 - fromRow);
            const to = position;
            const piece = board[fromRow][fromCol];
            if (piece.toLowerCase() === 'p' && ((myColor === 'white' && row === 0) || (myColor === 'black' && row === 7))) {
                document.getElementById('promotion-modal').style.display = 'flex';
                return new Promise(resolve => {
                    window.selectPromotion = function(piece) {
                        document.getElementById('promotion-modal').style.display = 'none';
                        socket.emit('move', { from, to, room, promotion: piece });
                        resolve();
                    };
                });
            } else {
                socket.emit('move', { from, to, room, promotion: null });
            }
            selectedSquare.classList.remove('selected');
            selectedSquare = null;
        }
    }
}

function handleTouchStart(event) {
    if (!username || (myColor !== turn) || (!room && !isBotGame) || !board) return;
    const square = event.target.closest('.square');
    if (!square) return;
    const row = parseInt(square.dataset.row);
    const col = parseInt(square.dataset.col);
    const piece = board[row][col];
    if (piece !== '.' && ((myColor === 'white' && isWhite(piece)) || (myColor === 'black' && !isWhite(piece)))) {
        const moves = gameType === 'checkers' ? getLegalMoves(row, col) : [];
        if (gameType !== 'checkers' || moves.length > 0) {
            selectedSquare = square;
            square.classList.add('selected');
        }
    }
}

function handleTouchEnd(event) {
    if (!selectedSquare || !board) return;
    const touchEndPos = { x: event.changedTouches[0].clientX, y: event.changedTouches[0].clientY };
    const square = document.elementFromPoint(touchEndPos.x, touchEndPos.y);
    if (square && square.classList.contains('square') && square !== selectedSquare) {
        const fromRow = parseInt(selectedSquare.dataset.row);
        const fromCol = parseInt(selectedSquare.dataset.col);
        const toRow = parseInt(square.dataset.row);
        const toCol = parseInt(square.dataset.col);
        const from = String.fromCharCode(97 + fromCol) + (8 - fromRow);
        const to = String.fromCharCode(97 + toCol) + (8 - toRow);
        if (gameType === 'checkers') {
            const moves = getLegalMoves(fromRow, fromCol);
            const move = moves.find(m => m.to.row === toRow && m.to.col === toCol);
            if (move) {
                socket.emit('move', { from, to, room });
            }
        } else {
            const piece = board[fromRow][fromCol];
            if (piece.toLowerCase() === 'p' && ((myColor === 'white' && row === 0) || (myColor === 'black' && row === 7))) {
                document.getElementById('promotion-modal').style.display = 'flex';
                return new Promise(resolve => {
                    window.selectPromotion = function(piece) {
                        document.getElementById('promotion-modal').style.display = 'none';
                        socket.emit('move', { from, to, room, promotion: piece });
                        resolve();
                    };
                });
            } else {
                socket.emit('move', { from, to, room, promotion: null });
            }
        }
    }
    selectedSquare.classList.remove('selected');
    selectedSquare = null;
}

function openBotConfigModal() {
    if (!username) {
        alert('Por favor, iniciá sesión primero.');
        return;
    }
    if (gameType === 'checkers') {
        alert('Jugar contra bot no está disponible para damas.');
        return;
    }
    document.getElementById('bot-config-modal').style.display = 'flex';
}

function closeBotConfigModal() {
    document.getElementById('bot-config-modal').style.display = 'none';
}

function startBotGame() {
    const timer = document.getElementById('bot-timer-select').value;
    const difficulty = document.getElementById('bot-difficulty-select').value;
    const player_color = document.getElementById('bot-player-color-select').value;
    socket.emit('play_with_bot', { timer, difficulty, player_color, color: '#FFFFFF' });
    closeBotConfigModal();
    roomSelection.style.display = 'none';
    chessboard.style.display = 'grid';
    gameButtons.style.display = 'block';
    timers.style.display = 'block';
    isBotGame = true;
}

function joinRoom() {
    if (!username) {
        alert('Por favor, iniciá sesión primero.');
        return;
    }
    room = document.getElementById('room-id').value.trim();
    const timer = document.getElementById('timer-select').value;
    const color = document.getElementById('color-select').value;
    if (!room) {
        alert('Por favor, ingresá un ID de sala.');
        return;
    }
    socket.emit('join', { room, timer, color, game_type: gameType });
}

function playWithBot() {
    openBotConfigModal();
}

function watchGame(roomId) {
    socket.emit('watch_game', { room: roomId });
}

function joinWaitlist() {
    if (!username) {
        alert('Por favor, iniciá sesión primero.');
        return;
    }
    const color = document.getElementById('color-select').value;
    socket.emit('join_waitlist', { color, avatar: currentAvatar });
    roomSelection.style.display = 'none';
    document.getElementById('waitlist').style.display = 'block';
    document.querySelector('.container').style.display = 'none';
    document.getElementById('global-chat').style.display = 'block';
}

function goBackFromWaitlist() {
    socket.emit('leave_waitlist');
    document.getElementById('waitlist').style.display = 'none';
    document.querySelector('.container').style.display = 'flex';
    roomSelection.style.display = 'block';
    document.getElementById('global-chat').style.display = 'block';
}

function goBackFromPrivateChat() {
    socket.emit('leave_private_chat', { room });
    document.getElementById('private-chat').style.display = 'none';
    document.querySelector('.container').style.display = 'flex';
    roomSelection.style.display = 'block';
    document.getElementById('global-chat').style.display = 'block';
    room = null;
}

function sendGlobalChatMessage() {
    if (!username) {
        alert('Por favor, iniciá sesión para usar el chat global.');
        return;
    }
    const input = document.getElementById('global-chat-input');
    const message = input.value.trim();
    if (message) {
        socket.emit('global_chat_message', { message: message });
        input.value = '';
    }
}

socket.on('new_global_message', data => {
    const chat = document.getElementById('global-chat-messages');
    if (chat) {
        const messageElement = document.createElement('div');
        messageElement.textContent = `[${data.timestamp}] ${data.username}: ${data.message}`;
        chat.appendChild(messageElement);
        chat.scrollTop = chat.scrollHeight;
    } else {
        console.error('Elemento global-chat-messages no encontrado');
    }
});

socket.on('bot_chat_message', data => {
    if (isBotGame) {
        const chat = document.getElementById('chat-messages');
        if (chat) {
            const messageElement = document.createElement('div');
            messageElement.textContent = `Stockfish: ${data.message}`;
            chat.appendChild(messageElement);
            chat.scrollTop = chat.scrollHeight;
        }
    }
});

socket.on('error', data => {
    console.log('Error recibido:', data.message);
    alert(data.message);
});

function sendPrivateMessage() {
    if (!username) {
        alert('Por favor, iniciá sesión primero.');
        return;
    }
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

function formatTime(seconds) {
    if (seconds === null || isNaN(seconds) || seconds < 0) return '--:--';
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
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

function sendMessage() {
    if (!username) {
        alert('Por favor, iniciá sesión primero.');
        return;
    }
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
    if (!username) {
        alert('Debes iniciar sesión para guardar una partida');
        return;
    }
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
    if (!username) {
        alert('Debes iniciar sesión para cargar una partida');
        return;
    }
    socket.emit('get_saved_games', { username });
    savedGamesDiv.style.display = 'block';
}

function loadGame(gameName) {
    if (!username) {
        alert('Debes iniciar sesión para cargar una partida');
        return;
    }
    socket.emit('load_game', { username, game_name: gameName });
}

function goBack() {
    if (room) {
        socket.emit('leave', { room });
    }
    roomSelection.style.display = 'block';
    document.querySelector('.container').style.display = 'flex';
    chessboard.style.display = 'none';
    checkersboard.style.display = 'none';
    chat.style.display = 'none';
    gameButtons.style.display = 'none';
    timers.style.display = 'none';
    savedGamesDiv.style.display = 'none';
    document.getElementById('global-chat').style.display = 'block';
    stopTimer();
    room = null;
    board = null;
    turn = null;
    selectedSquare = null;
    timeWhite = null;
    timeBlack = null;
    myColor = null;
    isBotGame = false;
    gameType = 'chess';
    updateTimers();
}

function selectOpponent(opponentSid) {
    socket.emit('select_opponent', { opponent_sid: opponentSid });
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
    roomSelection.style.display = 'none';
    document.getElementById('waitlist').style.display = 'none';
    document.getElementById('private-chat').style.display = 'none';
    document.getElementById('global-chat').style.display = 'none';
    document.getElementById('user-info').style.display = 'none';
    document.getElementById('neig-balance').textContent = '10000 Neig';
    document.getElementById('elo-level').textContent = 'ELO: 0 (Nivel 0)';
    goBack();
    stopVideoCall();
    socket.disconnect();
    socket.connect();
}

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
                document.getElementById('game-selection').style.display = 'block';
                document.getElementById('global-chat').style.display = 'block';
                document.getElementById('user-info').style.display = 'flex';
                socket.emit('join_user_room', { username });
                socket.emit('get_user_data', { username });
            } else {
                document.getElementById('register-error').textContent = data.error;
            }
        })
        .catch(error => {
            document.getElementById('register-error').textContent = 'Error en el registro. Intenta de nuevo.';
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

function setGameType(type) {
    gameType = type;
    localStorage.setItem('currentScreen', type === 'chess' ? 'chess-selection' : 'checkers-selection');
    document.getElementById('game-selection').style.display = 'none';
    roomSelection.style.display = 'block';
    document.getElementById('global-chat').style.display = 'block';
    document.getElementById('user-info').style.display = 'flex';
}

socket.on('connect', () => {
    console.log('Conectado al servidor');
    if (username) {
        socket.emit('join_user_room', { username });
        socket.emit('get_user_data', { username });
    }
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
    document.getElementById('game-selection').style.display = 'block';
    roomSelection.style.display = 'none';
    document.getElementById('global-chat').style.display = 'block';
    document.getElementById('user-info').style.display = 'flex';
    socket.emit('join_user_room', { username });
});

socket.on('login_error', data => {
    document.getElementById('login-error').textContent = data.error || data.message;
});

socket.on('online_players_update', players => {
    renderOnlinePlayers(players);
});

socket.on('color_assigned', data => {
    myColor = data.color;
    playerColors[data.color] = data.chosenColor;
});

socket.on('game_start', data => {
    gameType = data.game_type || 'chess';
    room = data.room;
    isBotGame = data.is_bot_game || false;
    board = data.board;
    turn = data.turn;
    timeWhite = data.time_white;
    timeBlack = data.time_black;
    playerColors = data.playerColors;
    previousBoard = JSON.parse(JSON.stringify(board));
    roomSelection.style.display = 'none';
    chessboard.style.display = gameType === 'chess' ? 'grid' : 'none';
    checkersboard.style.display = gameType === 'checkers' ? 'grid' : 'none';
    chat.style.display = 'block';
    gameButtons.style.display = 'block';
    timers.style.display = 'block';
    savedGamesDiv.style.display = 'none';
    document.querySelector('.container').style.display = 'flex';
    document.getElementById('global-chat').style.display = 'block';
    document.getElementById('user-info').style.display = 'flex';
    initializeBoard(gameType === 'checkers');
    renderBoard();
    updateTimers();
    if (timeWhite !== null && timeBlack !== null) startTimer();
});

socket.on('update_board', data => {
    board = data.board;
    turn = data.turn;
    previousBoard = JSON.parse(JSON.stringify(board));
    selectedSquare = null;
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
    gameType = data.game_type || 'chess';
    board = data.board;
    turn = data.turn;
    room = data.room;
    timeWhite = null;
    timeBlack = null;
    roomSelection.style.display = 'none';
    chessboard.style.display = gameType === 'chess' ? 'grid' : 'none';
    checkersboard.style.display = gameType === 'checkers' ? 'grid' : 'none';
    chat.style.display = 'block';
    gameButtons.style.display = 'block';
    timers.style.display = 'block';
    savedGamesDiv.style.display = 'none';
    document.querySelector('.container').style.display = 'flex';
    document.getElementById('global-chat').style.display = 'block';
    document.getElementById('user-info').style.display = 'flex';
    initializeBoard(gameType === 'checkers');
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
    document.getElementById('global-chat').style.display = 'block';
    document.getElementById('user-info').style.display = 'flex';
    document.getElementById('private-chat-messages').innerHTML = `<p>Conectado con ${data.opponent}</p>`;
});

socket.on('private_message', data => {
    const messages = document.getElementById('private-chat-messages');
    const message = document.createElement('div');
    message.textContent = `${data.username}: ${data.message}`;
    messages.appendChild(message);
    messages.scrollTop = messages.scrollHeight;
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
    initializeBoard(false);
    if (username) socket.emit('get_user_data', { username });
});

window.onload = () => {
    setTimeout(() => {
        document.getElementById('loading-screen').style.display = 'none';
        document.getElementById('login-register').style.display = 'block';
        document.querySelector('.container').style.display = 'none';
        document.getElementById('global-chat').style.display = 'none';
        document.getElementById('user-info').style.display = 'none';
        currentAvatar = '/static/default-avatar.png';
    }, 3000);
};
