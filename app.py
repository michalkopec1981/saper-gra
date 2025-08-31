from flask import Flask, render_template, request, jsonify, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO, emit
from datetime import datetime, timedelta
import threading
import os
import random

# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = 'bardzo-tajny-klucz-super-bezpieczny'
# Ścieżka do bazy danych w trwałym wolumenie Railway
# Railway domyślnie montuje wolumeny w /data
DB_DIR = '/data' 
DB_PATH = os.path.join(DB_DIR, 'db.sqlite3')

# Upewnij się, że folder /data istnieje, jeśli nie, stwórz go
if not os.path.exists(DB_DIR):
    os.makedirs(DB_DIR)

app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{DB_PATH}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)
socketio = SocketIO(app)

# --- Models ---
class Player(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    score = db.Column(db.Integer, default=0)
    warnings = db.Column(db.Integer, default=0)
    revealed_letters = db.Column(db.String(100), default='')

class Question(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    text = db.Column(db.String(255), nullable=False)
    option_a = db.Column(db.String(100))
    option_b = db.Column(db.String(100))
    option_c = db.Column(db.String(100))
    correct_answer = db.Column(db.String(1), nullable=False)
    letter_to_reveal = db.Column(db.String(1), nullable=False)

class GameState(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(50), unique=True, nullable=False)
    value = db.Column(db.String(100), nullable=False)

class QRCode(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code_identifier = db.Column(db.String(50), unique=True, nullable=False)
    is_red = db.Column(db.Boolean, default=False)
    claimed_by_player_id = db.Column(db.Integer, db.ForeignKey('player.id'), nullable=True)

class PlayerScan(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id'), nullable=False)
    qrcode_id = db.Column(db.Integer, db.ForeignKey('qr_code.id'), nullable=False)
    scan_time = db.Column(db.DateTime, nullable=False)

class PlayerAnswer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    player_id = db.Column(db.Integer, db.ForeignKey('player.id'), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey('question.id'), nullable=False)

# Global timer
game_timer = {
    'time_left': 0,
    'is_running': False,
    'end_time': None
}

# --- Routes ---
@app.route('/')
def index():
    return render_template('host.html')

@app.route('/player/<qr_code>')
def player_view(qr_code):
    return render_template('player.html', qr_code=qr_code)

@app.route('/host')
def host():
    return render_template('host.html')

@app.route('/display')
def display():
    return render_template('display.html')

@app.route('/qrcodes')
def list_qrcodes():
    qrcodes = QRCode.query.all()
    return render_template('qrcodes.html', qrcodes=qrcodes)

# --- API Endpoints ---

@app.route('/api/register_player', methods=['POST'])
def register_player():
    data = request.get_json()
    name = data.get('name')
    if not name: return jsonify({'error': 'Name is required'}), 400
    if Player.query.filter_by(name=name).first(): return jsonify({'error': 'Player name already exists'}), 409
    new_player = Player(name=name, score=0)
    db.session.add(new_player)
    db.session.commit()
    emit_leaderboard_update()
    return jsonify({'id': new_player.id, 'name': new_player.name}), 201

@app.route('/api/scan_qr', methods=['POST'])
def scan_qr():
    data = request.get_json()
    player_id, qr_code_identifier = data.get('player_id'), data.get('qr_code')
    if not player_id: return jsonify({'status': 'error', 'message': 'Brak ID gracza.'}), 400
    player, qr_code = db.session.get(Player, player_id), QRCode.query.filter_by(code_identifier=qr_code_identifier).first()
    if not player: return jsonify({'status': 'error', 'message': 'ID gracza jest nieprawidłowe.'}), 401
    if not qr_code: return jsonify({'status': 'error', 'message': 'Ten kod QR jest nieprawidłowy.'}), 404
    if not GameState.query.filter_by(key='game_active', value='True').first(): return jsonify({'status': 'error', 'message': 'Gra nie jest aktywna.'}), 403

    if qr_code.is_red:
        if qr_code.claimed_by_player_id: return jsonify({'status': 'error', 'message': 'Ten kod został już wykorzystany.'}), 403
        qr_code.claimed_by_player_id, player.score = player_id, player.score + 50
        db.session.commit()
        emit_leaderboard_update()
        return jsonify({'status': 'info', 'message': 'Zdobyłeś 50 punktów za czerwony kod!'})
    else: 
        last_scan = PlayerScan.query.filter_by(player_id=player_id, qrcode_id=qr_code.id).order_by(PlayerScan.scan_time.desc()).first()
        if last_scan and datetime.utcnow() < last_scan.scan_time + timedelta(minutes=5):
            wait_time = (last_scan.scan_time + timedelta(minutes=5) - datetime.utcnow()).seconds
            return jsonify({'status': 'wait', 'message': f'Odczekaj jeszcze {wait_time // 60} min {wait_time % 60} s.'}), 429
        
        db.session.add(PlayerScan(player_id=player_id, qrcode_id=qr_code.id, scan_time=datetime.utcnow()))
        db.session.commit()

        # --- ZMIENIONA LOGIKA ---
        # Sprawdź, czy Tetris jest aktywny
        tetris_state = GameState.query.filter_by(key='tetris_active').first()
        is_tetris_active = tetris_state and tetris_state.value == 'True'

        if is_tetris_active and qr_code_identifier in ["bialy1", "bialy2", "bialy3"]:
            return jsonify({'status': 'minigame', 'game': 'tetris'})
        else:
            answered_ids = [ans.question_id for ans in PlayerAnswer.query.filter_by(player_id=player_id).all()]
            question = Question.query.filter(Question.id.notin_(answered_ids)).order_by(db.func.random()).first()
            if not question: return jsonify({'status': 'info', 'message': 'Odpowiedziałeś na wszystkie pytania!'})
            return jsonify({'status': 'question', 'question': {'id': question.id, 'text': question.text, 'option_a': question.option_a, 'option_b': question.option_b, 'option_c': question.option_c}})

@app.route('/api/answer', methods=['POST'])
def process_answer():
    data = request.get_json()
    player_id, question_id, answer = data.get('player_id'), data.get('question_id'), data.get('answer')
    player, question = db.session.get(Player, player_id), db.session.get(Question, question_id)
    if not player or not question: return jsonify({'error': 'Invalid data'}), 404
    db.session.add(PlayerAnswer(player_id=player_id, question_id=question_id))
    if answer == question.correct_answer:
        player.score, player.revealed_letters = player.score + 10, player.revealed_letters + question.letter_to_reveal
        db.session.commit()
        emit_leaderboard_update()
        emit_password_update()
        return jsonify({'correct': True, 'letter': question.letter_to_reveal})
    else:
        player.score = max(0, player.score - 5)
        db.session.commit()
        emit_leaderboard_update()
        return jsonify({'correct': False})

@app.route('/api/minigame_reward', methods=['POST'])
def minigame_reward():
    data = request.get_json()
    player_id = data.get('player_id')
    player = db.session.get(Player, player_id)

    if not player:
        return jsonify({'error': 'Invalid player'}), 404

    reward_points = 15
    letter_to_reveal = 'T'

    player.score += reward_points
    if letter_to_reveal not in player.revealed_letters:
        player.revealed_letters += letter_to_reveal
    
    db.session.commit()
    
    emit_leaderboard_update()
    emit_password_update()
    
    return jsonify({'correct': True, 'letter': letter_to_reveal, 'points': reward_points})

# --- NOWY ENDPOINT DO ZARZĄDZANIA TETRISEM ---
@app.route('/api/competition/tetris', methods=['GET', 'POST'])
def manage_tetris():
    tetris_state = GameState.query.filter_by(key='tetris_active').first()
    if not tetris_state:
        # Fallback in case it's not initialized
        tetris_state = GameState(key='tetris_active', value='False')
        db.session.add(tetris_state)
        db.session.commit()

    if request.method == 'POST':
        data = request.get_json()
        new_state = data.get('active', False)
        tetris_state.value = 'True' if new_state else 'False'
        db.session.commit()
        socketio.emit('competition_state_update', {'game': 'tetris', 'active': new_state})
        return jsonify({'status': 'success', 'tetris_active': tetris_state.value == 'True'})
    
    return jsonify({'tetris_active': tetris_state.value == 'True'})

@app.route('/api/start_game', methods=['POST'])
def start_game():
    data = request.get_json()
    white_codes_count = int(data.get('white_codes_count', 5))
    red_codes_count = int(data.get('red_codes_count', 5))
    minutes = int(data.get('minutes', 10))
    
    db.session.query(PlayerScan).delete()
    db.session.query(PlayerAnswer).delete()
    db.session.query(Player).delete()
    db.session.query(QRCode).delete()

    for i in range(1, red_codes_count + 1): db.session.add(QRCode(code_identifier=f"czerwony{i}", is_red=True))
    for i in range(1, white_codes_count + 1): db.session.add(QRCode(code_identifier=f"bialy{i}", is_red=False))
        
    game_state = GameState.query.filter_by(key='game_active').first()
    if game_state: game_state.value = 'True'
    else: db.session.add(GameState(key='game_active', value='True'))
    
    game_timer['time_left'] = minutes * 60
    game_timer['is_running'] = True
    game_timer['end_time'] = datetime.now() + timedelta(seconds=game_timer['time_left'])
    
    db.session.commit()
    
    emit_leaderboard_update()
    emit_password_update()
    socketio.emit('game_state_update', get_full_game_state())
    socketio.emit('timer_started', {'time_left': game_timer['time_left']})
    
    return jsonify({'status': 'success', 'message': f'Gra rozpoczęta na {minutes} minut.'})

@app.route('/api/stop_game', methods=['POST'])
def stop_game():
    game_state = GameState.query.filter_by(key='game_active').first()
    if game_state: game_state.value = 'False'
    else: db.session.add(GameState(key='game_active', value='False'))
    
    game_timer['time_left'] = 0
    game_timer['is_running'] = False
    game_timer['end_time'] = None
    
    db.session.commit()
    
    socketio.emit('game_state_update', get_full_game_state())
    socketio.emit('timer_reset')
    return jsonify({'status': 'success', 'message': 'Gra została zakończona.'})

@app.route('/api/game/time/pause', methods=['POST'])
def pause_game_time():
    if game_timer['is_running']:
        game_timer['is_running'] = False
        game_timer['time_left'] = (game_timer['end_time'] - datetime.now()).total_seconds()
        socketio.emit('timer_paused', {'time_left': game_timer['time_left']})
    else: # Resume
        game_timer['is_running'] = True
        game_timer['end_time'] = datetime.now() + timedelta(seconds=game_timer['time_left'])
        socketio.emit('timer_started', {'time_left': game_timer['time_left']})
    socketio.emit('game_state_update', get_full_game_state())
    return jsonify({'status': 'success'})

@app.route('/api/game/state', methods=['GET'])
def get_game_state_api():
    game_active = GameState.query.filter_by(key='game_active', value='True').first() is not None
    return jsonify({
        'game_active': game_active,
        'is_timer_running': game_timer['is_running'],
        'time_left': game_timer['time_left']
    })

@app.route('/api/players', methods=['GET'])
def get_players():
    players = Player.query.order_by(Player.score.desc()).all()
    return jsonify([{'id': p.id, 'name': p.name, 'score': p.score, 'warnings': p.warnings} for p in players])

@app.route('/api/players/<int:player_id>', methods=['DELETE'])
def delete_player(player_id):
    player = db.session.get(Player, player_id)
    if player:
        db.session.delete(player)
        db.session.commit()
        emit_leaderboard_update()
    return jsonify({'status': 'success', 'message': 'Gracz usunięty'})

@app.route('/api/players/<int:player_id>/warn', methods=['POST'])
def warn_player(player_id):
    player = db.session.get(Player, player_id)
    if player:
        player.warnings += 1
        db.session.commit()
        socketio.emit('player_warned', {'player_id': player_id, 'warnings': player.warnings})
    return jsonify({'status': 'success', 'warnings': player.warnings if player else 0})

@app.route('/api/questions', methods=['GET', 'POST'])
def handle_questions():
    if request.method == 'POST':
        data = request.get_json()
        question = Question(text=data['text'], option_a=data['answers'][0], option_b=data['answers'][1], option_c=data['answers'][2] if len(data['answers']) > 2 else '', correct_answer=data['correctAnswer'], letter_to_reveal=data.get('letterToReveal', 'X'))
        db.session.add(question)
        db.session.commit()
        return jsonify({'status': 'success', 'message': 'Pytanie dodane', 'question_id': question.id})
    questions = Question.query.all()
    return jsonify([{'id': q.id, 'text': q.text, 'answers': [q.option_a, q.option_b, q.option_c], 'correctAnswer': q.correct_answer, 'letterToReveal': q.letter_to_reveal} for q in questions])

@app.route('/api/questions/<int:question_id>', methods=['DELETE'])
def delete_question(question_id):
    question = db.session.get(Question, question_id)
    if question:
        db.session.delete(question)
        db.session.commit()
    return jsonify({'status': 'success', 'message': 'Pytanie usunięte'})

# --- Helper functions ---
def get_full_game_state():
    game_active = GameState.query.filter_by(key='game_active', value='True').first() is not None
    password_setting = GameState.query.filter_by(key='password').first()
    password_value = password_setting.value if password_setting else "SAPEREVENT"
    revealed_letters_str = "".join(p.revealed_letters for p in Player.query.all())
    displayed_password = "".join([char if char in revealed_letters_str.upper() else "_" for char in password_value.upper()])
    return {'password': displayed_password, 'game_active': game_active, 'is_timer_running': game_timer['is_running']}

def emit_leaderboard_update():
    with app.app_context():
        players = Player.query.order_by(Player.score.desc()).all()
        socketio.emit('leaderboard_update', [{'name': p.name, 'score': p.score} for p in players])

def emit_password_update():
    with app.app_context():
        socketio.emit('password_update', get_full_game_state()['password'])

# Background task for timer
def update_timer():
    while True:
        if game_timer['is_running'] and game_timer.get('end_time'):
            now = datetime.now()
            if now >= game_timer['end_time']:
                game_timer['time_left'] = 0
                game_timer['is_running'] = False
                socketio.emit('timer_finished')
            else:
                game_timer['time_left'] = (game_timer['end_time'] - now).total_seconds()
            socketio.emit('timer_tick', {'time_left': game_timer['time_left']})
        socketio.sleep(1)

# SocketIO events
@socketio.on('connect')
def handle_connect():
    emit('game_state_update', get_full_game_state())
    emit_leaderboard_update()

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        # --- DODANA INICJALIZACJA STANU TETRISA ---
        if not GameState.query.filter_by(key='game_active').first(): db.session.add(GameState(key='game_active', value='False'))
        if not GameState.query.filter_by(key='password').first(): db.session.add(GameState(key='password', value='SAPEREVENT'))
        if not GameState.query.filter_by(key='tetris_active').first(): db.session.add(GameState(key='tetris_active', value='False'))
        db.session.commit()
    socketio.start_background_task(target=update_timer)
  if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=8000)




