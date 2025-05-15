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
const roomSelection = document.querySelector('.container #room-selection');
const checkersRoomSelection = document.querySelector('.checkers-container #room-selection');
const chat = document.getElementById('chat');
const gameButtons = document.getElementById('game-buttons');
const savedGamesDiv = document.getElementById('saved-games');
const timers = document.getElementById('timers');
const promotionModal = document.getElementById('promotion-modal');
const globalChat = document.getElementById('global-chat-container');
const userInfo = document.getElementById('user-info');

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
                promotionModal.style.display = 'flex';
                return new Promise(resolve => {
                    window.selectPromotion = function(piece) {
                        promotionModal.style.display = 'none';
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
                promotionModal.style.display = 'flex';
                return new Promise(resolve => {
                    window.selectPromotion = function(piece) {
                        promotionModal.style.display = 'none';
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
    localStorage.setItem('currentScreen', 'chess-bot-config');
    document.getElementById('bot-config-modal').style.display = 'block';
}

function closeBotConfigModal() {
    localStorage.setItem('currentScreen', 'chess');
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
    globalChat.style.display = 'block';
    userInfo.style.display = 'block';
    isBotGame = true;
}

function joinRoom() {
    if (!username) {
        alert('Por favor, iniciá sesión primero.');
        return;
    }
    const activeRoomSelection = gameType === 'chess' ? roomSelection : checkersRoomSelection;
    room = activeRoomSelection.querySelector('#room-id').value.trim();
    const timer = activeRoomSelection.querySelector('#timer-select').value;
    const color = activeRoomSelection.querySelector('#color-select').value;
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
    const activeRoomSelection = gameType === 'chess' ? roomSelection : checkersRoomSelection;
    const color = activeRoomSelection.querySelector('#color-select').value;
    socket.emit('join_waitlist', { color, avatar: currentAvatar });
    roomSelection.style.display = 'none';
    checkersRoomSelection.style.display = 'none';
    document.querySelector('.container').style.display = 'none';
    document.querySelector('.checkers-container').style.display = 'none';
    document.getElementById('waitlist').style.display = 'block';
    globalChat.style.display = 'block';
    userInfo.style.display = 'block';
}

function goBackFromWaitlist() {
    socket.emit('leave_waitlist');
    document.getElementById('waitlist').style.display = 'none';
    document.querySelector(gameType === 'chess' ? '.container' : '.checkers-container').style.display = 'flex';
    (gameType === 'chess' ? roomSelection : checkersRoomSelection).style.display = 'block';
    globalChat.style.display = 'block';
    userInfo.style.display = 'block';
}

function goBackFromPrivateChat() {
    socket.emit('leave_private_chat', { room });
    document.getElementById('private-chat').style.display = 'none';
    document.querySelector(gameType === 'chess' ? '.container' : '.checkers-container').style.display = 'flex';
    (gameType === 'chess' ? roomSelection : checkersRoomSelection).style.display = 'block';
    globalChat.style.display = 'block';
    userInfo.style.display = 'block';
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
        socket.emit('global_chat_message', { message });
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
    document.getElementById('neig-balance').innerHTML = `${neigBalance} <img src="/static/neig.png" alt="Neig">`;
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
    document.querySelector('.container').style.display = 'none';
    document.querySelector('.checkers-container').style.display = 'none';
    document.getElementById('game-selection').style.display = 'flex';
    chessboard.style.display = 'none';
    checkersboard.style.display = 'none';
    chat.style.display = 'none';
    gameButtons.style.display = 'none';
    timers.style.display = 'none';
    savedGamesDiv.style.display = 'none';
    globalChat.style.display = 'block';
    userInfo.style.display = 'block';
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
    fetch('/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: usernameInput, password })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            username = data.username;
            currentAvatar = data.avatar;
            localStorage.setItem('user', username);
            localStorage.setItem('currentScreen', 'game-selection');
            document.getElementById('login-register').style.display = 'none';
            document.getElementById('game-selection').style.display = 'flex';
            globalChat.style.display = 'block';
            userInfo.style.display = 'block';
            socket.emit('join_user_room', { username });
            socket.emit('get_user_data', { username });
        } else {
            document.getElementById('login-error').textContent = data.message;
        }
    });
}

function logout() {
    if (!username) return;
    fetch('/logout', { method: 'POST' })
    .then(() => {
        socket.emit('logout', { username });
        username = null;
        currentAvatar = null;
        neigBalance = 10000;
        eloPoints = 0;
        level = 0;
        localStorage.removeItem('user');
        localStorage.removeItem('currentScreen');
        document.getElementById('login-register').style.display = 'flex';
        document.querySelector('.container').style.display = 'none';
        document.querySelector('.checkers-container').style.display = 'none';
        document.getElementById('game-selection').style.display = 'none';
        document.getElementById('waitlist').style.display = 'none';
        document.getElementById('private-chat').style.display = 'none';
        globalChat.style.display = 'none';
        userInfo.style.display = 'none';
        document.getElementById('neig-balance').innerHTML = '10000 <img src="/static/neig.png" alt="Neig">';
        document.getElementById('elo-level').textContent = 'ELO: 0 (Nivel 0)';
        goBack();
        stopVideoCall();
        socket.disconnect();
        socket.connect();
    });
}

function register() {
    const formData = new FormData(document.getElementById('register-form'));
    fetch('/register', {
        method: 'POST',
        body: formData
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            username = data.username;
            currentAvatar = data.avatar;
            localStorage.setItem('user', username);
            localStorage.setItem('currentScreen', 'game-selection');
            document.getElementById('login-register').style.display = 'none';
            document.getElementById('game-selection').style.display = 'flex';
            globalChat.style.display = 'block';
            userInfo.style.display = 'block';
            socket.emit('join_user_room', { username });
            socket.emit('get_user_data', { username });
        } else {
            document.getElementById('register-error').textContent = data.message;
        }
    });
}

function setGameType(type) {
    gameType = type;
    localStorage.setItem('currentScreen', type);
    document.getElementById('game-selection').style.display = 'none';
    const container = document.querySelector('.container');
    const checkersContainer = document.querySelector('.checkers-container');
    if (type === 'chess') {
        container.style.display = 'flex';
        checkersContainer.style.display = 'none';
        roomSelection.style.display = 'block';
    } else {
        container.style.display = 'none';
        checkersContainer.style.display = 'flex';
        checkersRoomSelection.style.display = 'block';
    }
    globalChat.style.display = 'block';
    userInfo.style.display = 'block';
}

socket.on('connect', () => {
    console.log('Conectado al servidor');
    const user = localStorage.getItem('user');
    if (user) {
        fetch('/check_session', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username: user })
        })
        .then(response => response.json())
        .then(data => {
            if (data.authenticated) {
                username = user;
                document.getElementById('login-register').style.display = 'none';
                const currentScreen = localStorage.getItem('currentScreen');
                if (currentScreen === 'chess') {
                    setGameType('chess');
                } else if (currentScreen === 'checkers') {
                    setGameType('checkers');
                } else if (currentScreen === 'chess-bot-config') {
                    setGameType('chess');
                    openBotConfigModal();
                } else {
                    document.getElementById('game-selection').style.display = 'flex';
                }
                socket.emit('join_user_room', { username });
                socket.emit('get_user_data', { username });
            } else {
                localStorage.removeItem('user');
                localStorage.removeItem('currentScreen');
                document.getElementById('login-register').style.display = 'flex';
                globalChat.style.display = 'none';
                userInfo.style.display = 'none';
            }
        });
    }
});

socket.on('login_success', data => {
    username = data.username;
    currentAvatar = data.avatar;
    neigBalance = data.neig;
    eloPoints = data.elo;
    level = data.level;
    updateUserData({ neig: neigBalance, elo: eloPoints, level: level });
    localStorage.setItem('user', username);
    localStorage.setItem('currentScreen', 'game-selection');
    document.getElementById('login-register').style.display = 'none';
    document.getElementById('game-selection').style.display = 'flex';
    globalChat.style.display = 'block';
    userInfo.style.display = 'block';
    socket.emit('join_user_room', { username });
});

socket.on('login_error', data => {
    document.getElementById('login-error').textContent = data.error || data.message;
});

socket.on('online_players_update', players => {
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
        p.style.cursor = 'pointer';
        p.onclick = () => selectOpponent(player.sid);
        onlineDiv.appendChild(p);
    });
});

socket.on('user_data', data => {
    updateUserData(data);
});

socket.on('join_success', data => {
    room = data.room;
    myColor = data.color;
    playerColors = data.player_colors || { white: '#FFFFFF', black: '#000000' };
    timeWhite = data.timer;
    timeBlack = data.timer;
    board = data.board;
    turn = data.turn;
    const targetBoard = gameType === 'chess' ? chessboard : checkersboard;
    const activeRoomSelection = gameType === 'chess' ? roomSelection : checkersRoomSelection;
    const container = gameType === 'chess' ? document.querySelector('.container') : document.querySelector('.checkers-container');
    
    container.style.display = 'flex';
    activeRoomSelection.style.display = 'none';
    targetBoard.style.display = 'grid';
    chat.style.display = 'block';
    gameButtons.style.display = 'block';
    timers.style.display = 'block';
    globalChat.style.display = 'block';
    userInfo.style.display = 'block';
    
    initializeBoard(gameType === 'checkers');
    renderBoard();
    updateTimers();
    if (data.timer > 0) startTimer();
});

socket.on('game_state', data => {
    board = data.board;
    turn = data.turn;
    timeWhite = data.time_white;
    timeBlack = data.time_black;
    renderBoard();
    updateTimers();
    if (data.timer > 0 && turn) startTimer();
    else stopTimer();
});

socket.on('move', data => {
    board = data.board;
    turn = data.turn;
    timeWhite = data.time_white;
    timeBlack = data.time_black;
    renderBoard();
    updateTimers();
    if (data.timer > 0) startTimer();
});

socket.on('game_over', data => {
    stopTimer();
    alert(`Juego terminado: ${data.result}`);
    if (data.elo) {
        eloPoints = data.elo;
        level = data.level;
        updateUserData({ neig: neigBalance, elo: eloPoints, level });
    }
    goBack();
});

socket.on('chat_message', data => {
    const chatMessages = document.getElementById('chat-messages');
    const messageElement = document.createElement('div');
    messageElement.textContent = `[${data.timestamp}] ${data.username}: ${data.message}`;
    chatMessages.appendChild(messageElement);
    chatMessages.scrollTop = chatMessages.scrollHeight;
});

socket.on('audio_message', data => {
    const chatMessages = document.getElementById('chat-messages');
    const audioElement = document.createElement('audio');
    audioElement.controls = true;
    audioElement.src = `data:audio/webm;base64,${data.audio}`;
    const messageElement = document.createElement('div');
    messageElement.textContent = `[${data.timestamp}] ${data.username}: `;
    messageElement.appendChild(audioElement);
    chatMessages.appendChild(messageElement);
    chatMessages.scrollTop = chatMessages.scrollHeight;
});

socket.on('video_signal', data => {
    if (peer) {
        peer.signal(data.signal);
    }
});

socket.on('video_stop', () => {
    stopVideoCall();
});

socket.on('saved_games', data => {
    savedGamesDiv.innerHTML = '';
    data.games.forEach(game => {
        const button = document.createElement('button');
        button.textContent = game.name;
        button.onclick = () => loadGame(game.name);
        savedGamesDiv.appendChild(button);
    });
});

socket.on('game_loaded', data => {
    room = data.room;
    board = data.board;
    turn = data.turn;
    myColor = data.color;
    timeWhite = data.timer;
    timeBlack = data.timer;
    const targetBoard = gameType === 'chess' ? chessboard : checkersboard;
    const activeRoomSelection = gameType === 'chess' ? roomSelection : checkersRoomSelection;
    const container = gameType === 'chess' ? document.querySelector('.container') : document.querySelector('.checkers-container');
    
    container.style.display = 'flex';
    activeRoomSelection.style.display = 'none';
    targetBoard.style.display = 'grid';
    chat.style.display = 'block';
    gameButtons.style.display = 'block';
    timers.style.display = 'block';
    savedGamesDiv.style.display = 'none';
    globalChat.style.display = 'block';
    userInfo.style.display = 'block';
    
    initializeBoard(gameType === 'checkers');
    renderBoard();
    updateTimers();
    if (data.timer > 0) startTimer();
});

socket.on('waitlist_update', data => {
    const waitlistPlayers = document.getElementById('waitlist-players');
    waitlistPlayers.innerHTML = '';
    data.players.forEach(player => {
        const div = document.createElement('div');
        div.className = 'player-item';
        const img = document.createElement('img');
        img.src = player.avatar || '/static/default-avatar.png';
        img.onerror = () => img.src = '/static/default-avatar.png';
        div.appendChild(img);
        div.appendChild(document.createTextNode(player.username));
        div.onclick = () => selectOpponent(player.sid);
        waitlistPlayers.appendChild(div);
    });
});

socket.on('private_chat', data => {
    room = data.room;
    const container = document.querySelector('.container');
    const checkersContainer = document.querySelector('.checkers-container');
    container.style.display = 'none';
    checkersContainer.style.display = 'none';
    roomSelection.style.display = 'none';
    checkersRoomSelection.style.display = 'none';
    document.getElementById('waitlist').style.display = 'none';
    document.getElementById('private-chat').style.display = 'block';
    globalChat.style.display = 'block';
    userInfo.style.display = 'block';
    document.getElementById('private-chat-messages').innerHTML = '';
});

socket.on('private_message', data => {
    const privateChatMessages = document.getElementById('private-chat-messages');
    const messageElement = document.createElement('div');
    messageElement.textContent = `[${data.timestamp}] ${data.username}: ${data.message}`;
    privateChatMessages.appendChild(messageElement);
    privateChatMessages.scrollTop = privateChatMessages.scrollHeight;
});

socket.on('conditions_accepted', data => {
    room = data.room;
    myColor = data.color;
    playerColors = data.player_colors || { white: '#FFFFFF', black: '#000000' };
    timeWhite = data.timer;
    timeBlack = data.timer;
    board = data.board;
    turn = data.turn;
    const targetBoard = gameType === 'chess' ? chessboard : checkersboard;
    const container = gameType === 'chess' ? document.querySelector('.container') : document.querySelector('.checkers-container');
    
    container.style.display = 'flex';
    document.getElementById('private-chat').style.display = 'none';
    targetBoard.style.display = 'grid';
    chat.style.display = 'block';
    gameButtons.style.display = 'block';
    timers.style.display = 'block';
    globalChat.style.display = 'block';
    userInfo.style.display = 'block';
    
    initializeBoard(gameType === 'checkers');
    renderBoard();
    updateTimers();
    if (data.timer > 0) startTimer();
});

socket.on('player_disconnected', () => {
    alert('El otro jugador se ha desconectado.');
    goBack();
});

document.getElementById('login-form').addEventListener('submit', e => {
    e.preventDefault();
    const formData = new FormData(e.target);
    const usernameInput = formData.get('username');
    const password = formData.get('password');
    login(usernameInput, password);
});

document.getElementById('register-form').addEventListener('submit', e => {
    e.preventDefault();
    register();
});

document.getElementById('recover-form').addEventListener('submit', e => {
    e.preventDefault();
    const formData = new FormData(e.target);
    const usernameInput = formData.get('username');
    fetch('/recover_password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: usernameInput })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            document.getElementById('recover-form').style.display = 'none';
            document.getElementById('reset-form').style.display = 'block';
        } else {
            document.getElementById('recover-error').textContent = data.message;
        }
    });
});

document.getElementById('reset-form').addEventListener('submit', e => {
    e.preventDefault();
    const formData = new FormData(e.target);
    const code = formData.get('code');
    const newPassword = formData.get('new-password');
    fetch('/reset_password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code, new_password: newPassword })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            hideRecoverPassword();
        } else {
            document.getElementById('reset-error').textContent = data.message;
        }
    });
});

document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('loading-screen').style.display = 'none';
    const user = localStorage.getItem('user');
    if (user) {
        fetch('/check_session', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username: user })
        })
        .then(response => response.json())
        .then(data => {
            if (data.authenticated) {
                username = user;
                document.getElementById('login-register').style.display = 'none';
                const currentScreen = localStorage.getItem('currentScreen');
                if (currentScreen === 'chess') {
                    setGameType('chess');
                } else if (currentScreen === 'checkers') {
                    setGameType('checkers');
                } else if (currentScreen === 'chess-bot-config') {
                    setGameType('chess');
                    openBotConfigModal();
                } else {
                    document.getElementById('game-selection').style.display = 'flex';
                }
                globalChat.style.display = 'block';
                userInfo.style.display = 'block';
                socket.emit('join_user_room', { username });
                socket.emit('get_user_data', { username });
            } else {
                localStorage.removeItem('user');
                localStorage.removeItem('currentScreen');
                document.getElementById('login-register').style.display = 'flex';
                globalChat.style.display = 'none';
                userInfo.style.display = 'none';
            }
        });
    } else {
        document.getElementById('login-register').style.display = 'flex';
        globalChat.style.display = 'none';
        userInfo.style.display = 'none';
    }
});
