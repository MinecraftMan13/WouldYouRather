import json
import random
import os
import time
import queue
from flask import Flask, render_template, request, jsonify, session, redirect, url_for, Response
from dotenv import load_dotenv
from waitress import serve



# -----------------------------------------------
# APP SETUP
# -----------------------------------------------

app = Flask(__name__)

# SECRET KEY — Flask uses this to securely sign the session cookie.
# The session is how Flask remembers you're logged in between page loads.
# In a real production app you'd move this to an environment variable,
# but this is fine for a personal project.
load_dotenv()
app.secret_key = os.getenv("SECRET_KEY")
ADMIN_USERNAME  = os.getenv("ADMIN_USERNAME")
ADMIN_PASSWORD  = os.getenv("ADMIN_PASSWORD")

# File paths
QUESTIONS_FILE = "questions.json"
IP_LOG_FILE    = "ip_log.json"
LOBBIES_FILE   = "lobbies.json"
USER_VOTES_FILE = "user_votes.json"


def load_lobbies():
    if not os.path.exists(LOBBIES_FILE):
        return {}
    with open(LOBBIES_FILE, "r") as f:
        return json.load(f)


def save_lobbies(lobbies):
    with open(LOBBIES_FILE, "w") as f:
        json.dump(lobbies, f, indent=2)


def generate_lobby_id():
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    lobbies = load_lobbies()
    while True:
        lobby_id = "".join(random.choice(alphabet) for _ in range(6))
        if lobby_id not in lobbies:
            return lobby_id


def sanitize_nickname(nickname):
    nickname = (nickname or "").strip()
    nickname = "".join(ch for ch in nickname if ch.isalnum() or ch.isspace())
    return nickname[:16].strip()


def format_timestamp(timestamp):
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(timestamp))


def prepare_lobbies_for_admin(lobbies, question_map):
    sorted_lobbies = []
    for lobby in sorted(lobbies.values(), key=lambda lobby: lobby.get("created_at", 0), reverse=True):
        host = next(iter(lobby.get("players", {})), "—")
        current_question = None
        question_ids = lobby.get("question_ids", [])
        current_index = lobby.get("current_index", 0)
        if current_index < len(question_ids):
            current_question = question_map.get(question_ids[current_index])

        lobby_copy = dict(lobby)
        lobby_copy["host"] = host
        lobby_copy["current_question"] = current_question
        lobby_copy["created_at_str"] = format_timestamp(lobby.get("created_at", time.time()))
        sorted_lobbies.append(lobby_copy)
    return sorted_lobbies


def get_lobby_question(lobby):
    question_ids = lobby.get("question_ids", [])
    current_index = lobby.get("current_index", 0)
    if current_index >= len(question_ids):
        return None
    questions = load_questions()
    return next((q for q in questions if q["id"] == question_ids[current_index]), None)


def update_player_timestamp(player):
    now = time.time()
    player["last_seen"] = now
    if "joined_at" not in player:
        player["joined_at"] = now


def remove_stale_players(lobby, max_idle_seconds=120):
    now = time.time()
    for name, info in list(lobby.get("players", {}).items()):
        if info.get("choice") is not None:
            continue
        last_seen = info.get("last_seen", info.get("joined_at", now))
        if now - last_seen > max_idle_seconds:
            del lobby["players"][name]


def refresh_lobby_state(lobby):
    if lobby.get("players"):
        lobby.pop("empty_since", None)
    else:
        lobby.setdefault("empty_since", time.time())


def cleanup_lobbies(lobbies):
    now = time.time()
    for lobby_id in list(lobbies.keys()):
        lobby = lobbies[lobby_id]
        remove_stale_players(lobby)
        refresh_lobby_state(lobby)
        if not lobby.get("players") and now - lobby.get("empty_since", now) > 600:
            del lobbies[lobby_id]


# -----------------------------------------------
# SSE — LIVE VOTE COUNTER
#
# Server-Sent Events work like this:
#   - Each browser that loads the page opens a
#     persistent connection to /stream
#   - We keep a list of "listener" queues, one per
#     connected browser
#   - When a vote comes in, we push a message into
#     every queue
#   - Each browser receives it instantly and shows
#     the toast notification
# -----------------------------------------------

# Global list of queues — one per connected browser
listeners = []

def push_vote_event(option_text):
    """
    Send a vote notification to every connected browser.
    Each listener is a Queue object. We put a message in
    each one and the SSE stream picks it up.
    """
    dead = []
    for q in listeners:
        try:
            q.put_nowait(option_text)
        except Exception:
            # Queue is full or broken — mark it for removal
            dead.append(q)
    for q in dead:
        listeners.remove(q)


# -----------------------------------------------
# HELPER FUNCTIONS — QUESTIONS
# -----------------------------------------------

def load_questions():
    """Read questions.json and return it as a Python list."""
    with open(QUESTIONS_FILE, "r") as f:
        return json.load(f)

def save_questions(questions):
    """Write the updated questions list back to questions.json."""
    with open(QUESTIONS_FILE, "w") as f:
        json.dump(questions, f, indent=2)

def next_id(questions):
    all_questions = questions
    if not all_questions:
        return 1
    return max(q["id"] for q in all_questions) + 1


# -----------------------------------------------
# HELPER FUNCTIONS — IP LOG
# -----------------------------------------------

def load_ip_log():
    if not os.path.exists(IP_LOG_FILE):
        return {}
    with open(IP_LOG_FILE, "r") as f:
        return json.load(f)

def load_user_votes():
    if not os.path.exists(USER_VOTES_FILE):
        return {}
    with open(USER_VOTES_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_user_votes(data):
    with open(USER_VOTES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def save_ip_log(ip_log):
    with open(IP_LOG_FILE, "w") as f:
        json.dump(ip_log, f, indent=2)

def get_client_ip():
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.remote_addr

def has_voted(ip, question_id):
    ip_log = load_ip_log()
    return question_id in ip_log.get(ip, [])

def record_vote(ip, question_id):
    ip_log = load_ip_log()
    if ip not in ip_log:
        ip_log[ip] = []
    ip_log[ip].append(question_id)
    save_ip_log(ip_log)


def record_user_vote(ip, question_id, choice):
    """Store per-IP vote records with choice so users can view/change them."""
    uv = load_user_votes()
    if ip not in uv:
        uv[ip] = []
    # Append a vote record
    uv[ip].append({
        "question_id": question_id,
        "choice": choice,
        "ts": time.time()
    })
    save_user_votes(uv)


def get_user_votes_for_ip(ip):
    uv = load_user_votes()
    return uv.get(ip, [])


# -----------------------------------------------
# HELPER — LOGIN GUARD
# -----------------------------------------------

def is_logged_in():
    """
    Returns True if the current session is marked as logged in.
    session is a dict Flask attaches to each visitor via a cookie.
    We set session["admin"] = True on successful login.
    """
    return session.get("admin") is True


# -----------------------------------------------
# ADMIN ROUTES
# -----------------------------------------------
@app.route("/")
def index():
    print(f"Connection established from: {request.remote_addr}")
    questions    = load_questions()
    ip           = get_client_ip()
    ip_log       = load_ip_log()
    answered_ids = ip_log.get(ip, [])

    # Only show approved (non-pending) questions
    live_questions = [q for q in questions if not q.get("pending", False)]
    unanswered     = [q for q in live_questions if q["id"] not in answered_ids]

    if not unanswered:
        unanswered = live_questions if live_questions else questions

    question = random.choice(unanswered)
    return render_template("index.html", question=question)


@app.route("/question/<int:question_id>")
def question_page(question_id):
    """
    Direct link to a specific question — used by the share feature.
    e.g. /question/4 always shows question #4.
    If the question doesn't exist, fall back to the home page.
    """
    questions = load_questions()
    question  = next((q for q in questions if q["id"] == question_id), None)

    if not question or question.get("pending", False):
        return redirect(url_for("index"))

    return render_template("index.html", question=question)


@app.route("/challenge/create", methods=["POST"])
def create_challenge():
    nickname = sanitize_nickname(request.form.get("nickname", ""))
    if not nickname:
        return redirect(url_for("index"))

    questions = load_questions()
    live_questions = [q for q in questions if not q.get("pending", False)]
    if not live_questions:
        return redirect(url_for("index"))

    question_ids = [q["id"] for q in live_questions]
    random.shuffle(question_ids)
    question_ids = question_ids[:10]

    lobby_id = generate_lobby_id()
    lobbies = load_lobbies()
    cleanup_lobbies(lobbies)
    lobbies[lobby_id] = {
        "id": lobby_id,
        "question_ids": question_ids,
        "current_index": 0,
        "players": {
            nickname: {"choice": None, "joined_at": time.time(), "last_seen": time.time()}
        },
        "created_at": time.time()
    }
    save_lobbies(lobbies)
    return redirect(url_for("challenge", lobby_id=lobby_id, nickname=nickname))


@app.route("/challenge/<lobby_id>/leave")
def leave_lobby(lobby_id):
    nickname = sanitize_nickname(request.args.get("nickname", ""))
    lobbies = load_lobbies()
    cleanup_lobbies(lobbies)
    save_lobbies(lobbies)
    lobby = lobbies.get(lobby_id)
    if lobby and nickname in lobby.get("players", {}):
        del lobby["players"][nickname]
        refresh_lobby_state(lobby)
        save_lobbies(lobbies)
    return redirect(url_for("index"))


@app.route("/challenge/<lobby_id>")
def challenge(lobby_id):
    lobbies = load_lobbies()
    cleanup_lobbies(lobbies)
    save_lobbies(lobbies)
    lobby = lobbies.get(lobby_id)
    if not lobby:
        return redirect(url_for("index"))

    nickname = sanitize_nickname(request.args.get("nickname", ""))
    if not nickname:
        return render_template("challenge.html", join_only=True,
                               lobby_id=lobby_id,
                               players=lobby.get("players", {}),
                               error=None)

    if nickname not in lobby["players"]:
        if len(lobby["players"]) >= 2:
            return render_template("challenge.html", join_only=True,
                                   lobby_id=lobby_id,
                                   players=lobby.get("players", {}),
                                   error="This lobby is already full.")
        lobby["players"][nickname] = {"choice": None, "joined_at": time.time(), "last_seen": time.time()}

    update_player_timestamp(lobby["players"][nickname])
    save_lobbies(lobbies)

    question = get_lobby_question(lobby)
    if question is None:
        return render_template("challenge.html", join_only=False,
                               finished=True,
                               lobby=lobby,
                               nickname=nickname,
                               players=lobby.get("players", {}))

    return render_template("challenge.html", join_only=False,
                           finished=False,
                           lobby=lobby,
                           nickname=nickname,
                           players=lobby.get("players", {}),
                           question=question)


@app.route("/challenge/<lobby_id>/status")
def challenge_status(lobby_id):
    lobbies = load_lobbies()
    cleanup_lobbies(lobbies)
    save_lobbies(lobbies)
    lobby = lobbies.get(lobby_id)
    if not lobby:
        return jsonify({"error": "Lobby not found"}), 404

    nickname = sanitize_nickname(request.args.get("nickname", ""))
    if nickname in lobby.get("players", {}):
        update_player_timestamp(lobby["players"][nickname])
        save_lobbies(lobbies)

    question = get_lobby_question(lobby)
    return jsonify({
        "lobby_id": lobby_id,
        "question": question,
        "players": {name: {"choice": info.get("choice")} for name, info in lobby.get("players", {}).items()},
        "both_voted": bool(question) and lobby.get("players") and all(info.get("choice") for info in lobby.get("players", {}).values()),
        "finished": question is None,
        "current_index": lobby.get("current_index", 0)
    })


@app.route("/challenge/<lobby_id>/vote", methods=["POST"])
def challenge_vote(lobby_id):
    data = request.json or {}
    nickname = sanitize_nickname(data.get("nickname", ""))
    choice = data.get("choice")

    if choice not in {"a", "b"}:
        return jsonify({"error": "Invalid choice"}), 400

    lobbies = load_lobbies()
    cleanup_lobbies(lobbies)
    lobby = lobbies.get(lobby_id)
    if not lobby:
        return jsonify({"error": "Lobby not found"}), 404

    if nickname not in lobby.get("players", {}):
        return jsonify({"error": "Player not in lobby"}), 400

    question = get_lobby_question(lobby)
    if question is None:
        return jsonify({"error": "Challenge is finished"}), 400

    update_player_timestamp(lobby["players"][nickname])
    lobby["players"][nickname]["choice"] = choice
    save_lobbies(lobbies)

    return jsonify({
        "players": {name: {"choice": info.get("choice")} for name, info in lobby.get("players", {}).items()},
        "both_voted": bool(lobby.get("players")) and all(info.get("choice") for info in lobby.get("players", {}).values())
    })


@app.route("/challenge/<lobby_id>/next", methods=["POST"])
def challenge_next(lobby_id):
    lobbies = load_lobbies()
    cleanup_lobbies(lobbies)
    lobby = lobbies.get(lobby_id)
    if not lobby:
        return jsonify({"error": "Lobby not found"}), 404

    if not lobby.get("players"):
        return jsonify({"error": "No active players in lobby."}), 400

    if not all(info.get("choice") for info in lobby.get("players", {}).values()):
        return jsonify({"error": "Both players must vote before continuing."}), 400

    lobby["current_index"] = lobby.get("current_index", 0) + 1
    for info in lobby.get("players", {}).values():
        info["choice"] = None
        update_player_timestamp(info)

    save_lobbies(lobbies)
    return jsonify({"finished": get_lobby_question(lobby) is None})


@app.route("/vote", methods=["POST"])
def vote():
    data        = request.json
    question_id = data.get("question_id")
    choice      = data.get("choice")
    ip          = get_client_ip()

    if has_voted(ip, question_id):
        return jsonify({"already_voted": True})

    questions = load_questions()

    for question in questions:
        if question["id"] == question_id:
            if choice == "a":
                question["votes_a"] += 1
                voted_text = question["option_a"]
            elif choice == "b":
                question["votes_b"] += 1
                voted_text = question["option_b"]

            save_questions(questions)
            record_vote(ip, question_id)
            # Also save the user's choice so they can view/change it later
            try:
                record_user_vote(ip, question_id, choice)
            except Exception:
                # non-fatal; continue even if user vote recording fails
                pass

            # Notify all connected browsers about the new vote
            push_vote_event(voted_text)

            total     = question["votes_a"] + question["votes_b"]
            percent_a = round((question["votes_a"] / total) * 100) if total > 0 else 0
            percent_b = round((question["votes_b"] / total) * 100) if total > 0 else 0

            return jsonify({
                "already_voted": False,
                "votes_a":   question["votes_a"],
                "votes_b":   question["votes_b"],
                "percent_a": percent_a,
                "percent_b": percent_b
            })

    return jsonify({"error": "Question not found"}), 404


@app.route("/my-history")
def my_history():
    ip = get_client_ip()
    records = get_user_votes_for_ip(ip)
    questions = load_questions()
    qmap = {q["id"]: q for q in questions}

    out = []
    for r in records:
        qid = r.get("question_id")
        q = qmap.get(qid)
        if not q:
            continue
        out.append({
            "question_id": qid,
            "option_a": q.get("option_a"),
            "option_b": q.get("option_b"),
            "choice": r.get("choice"),
            "ts": r.get("ts"),
            "votes_a": q.get("votes_a", 0),
            "votes_b": q.get("votes_b", 0)
        })

    return jsonify(out)


@app.route("/change-vote", methods=["POST"])
def change_vote():
    data = request.json or {}
    question_id = data.get("question_id")
    new_choice = data.get("choice")
    ip = get_client_ip()

    if new_choice not in ("a", "b"):
        return jsonify({"error": "Invalid choice"}), 400

    # Find user's most recent record for this question
    records = get_user_votes_for_ip(ip)
    found = None
    for r in reversed(records):
        if r.get("question_id") == question_id:
            found = r
            break

    if not found:
        return jsonify({"error": "No previous vote found for this question"}), 404

    old_choice = found.get("choice")
    if old_choice == new_choice:
        return jsonify({"ok": True, "message": "No change"})

    # Adjust counts on the question
    questions = load_questions()
    for question in questions:
        if question["id"] == question_id:
            # decrement old
            if old_choice == "a" and question.get("votes_a", 0) > 0:
                question["votes_a"] = max(0, question.get("votes_a", 0) - 1)
            if old_choice == "b" and question.get("votes_b", 0) > 0:
                question["votes_b"] = max(0, question.get("votes_b", 0) - 1)
            # increment new
            if new_choice == "a":
                question["votes_a"] = question.get("votes_a", 0) + 1
                changed_text = question.get("option_a")
            else:
                question["votes_b"] = question.get("votes_b", 0) + 1
                changed_text = question.get("option_b")

            save_questions(questions)

            # update user record
            uv = load_user_votes()
            # update the most recent matching record in uv[ip]
            if ip in uv:
                for r in reversed(uv[ip]):
                    if r.get("question_id") == question_id:
                        r["choice"] = new_choice
                        r["ts"] = time.time()
                        break
                save_user_votes(uv)

            # Notify others about changed vote (best-effort)
            try:
                push_vote_event(changed_text)
            except Exception:
                pass

            total = question.get("votes_a", 0) + question.get("votes_b", 0)
            percent_a = round((question.get("votes_a", 0) / total) * 100) if total > 0 else 0
            percent_b = round((question.get("votes_b", 0) / total) * 100) if total > 0 else 0

            return jsonify({
                "ok": True,
                "votes_a": question.get("votes_a", 0),
                "votes_b": question.get("votes_b", 0),
                "percent_a": percent_a,
                "percent_b": percent_b
            })

    return jsonify({"error": "Question not found"}), 404


@app.route("/stream")
def stream():
    """
    Server-Sent Events endpoint.

    When a browser connects here, we:
      1. Create a new Queue for it
      2. Add it to the global listeners list
      3. Keep the connection open, yielding messages as they arrive
      4. Remove the queue when the browser disconnects

    The browser connects to this once on page load and
    stays connected — no polling needed.
    """
    def event_generator():
        # Create a personal queue for this browser connection
        q = queue.Queue(maxsize=10)
        listeners.append(q)

        try:
            while True:
                try:
                    # Wait up to 25 seconds for a vote event.
                    # If nothing comes, send a keep-alive comment
                    # so the connection doesn't time out.
                    message = q.get(timeout=25)
                    # SSE format: "data: <message>\n\n"
                    yield f"data: {message}\n\n"
                except queue.Empty:
                    # Keep-alive ping — browsers ignore lines starting with ':'
                    yield ": keep-alive\n\n"
        except GeneratorExit:
            # Browser disconnected — clean up the queue
            if q in listeners:
                listeners.remove(q)

    return Response(
        event_generator(),
        mimetype="text/event-stream",
        headers={
            # Disable caching so the browser always opens a fresh connection
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no"   # important for Nginx proxies
        }
    )


@app.route("/submit", methods=["GET", "POST"])
def submit():
    """
    Public page where anyone can submit a question for review.
    GET  — show the submission form
    POST — save the question as pending=True
    """
    if request.method == "POST":
        option_a = request.form.get("option_a", "").strip()
        option_b = request.form.get("option_b", "").strip()

        if not option_a or not option_b:
            return render_template("submit.html", error="Both options are required.")

        questions = load_questions()

        # pending=True marks it as unreviewed.
        # It won't appear in the public question pool until approved.
        new_question = {
            "id":       next_id(questions),
            "option_a": option_a,
            "option_b": option_b,
            "votes_a":  0,
            "votes_b":  0,
            "pending":  True
        }

        questions.append(new_question)
        save_questions(questions)

        return render_template("submit.html", success=True)

    return render_template("submit.html")


# -----------------------------------------------
# ADMIN ROUTES
# -----------------------------------------------

@app.route("/admin", methods=["GET", "POST"])

def admin_login():
    if is_logged_in():
        return redirect(url_for("admin_dashboard"))

    error = None
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session["admin"] = True
            return redirect(url_for("admin_dashboard"))
        else:
            error = "Invalid username or password."

    return render_template("admin.html", view="login", error=error)


@app.route("/admin/dashboard")
def admin_dashboard():
    if not is_logged_in():
        return redirect(url_for("admin_login"))

    questions = load_questions()
    lobbies = load_lobbies()
    cleanup_lobbies(lobbies)
    save_lobbies(lobbies)

    # Split into live and pending so the template can show them separately
    live    = [q for q in questions if not q.get("pending", False)]
    pending = [q for q in questions if q.get("pending", False)]
    question_map = {q["id"]: q for q in questions}
    sorted_lobbies = prepare_lobbies_for_admin(lobbies, question_map)

    new_lobby = request.args.get("new_lobby")
    active_tab = request.args.get("tab", "questions")
    return render_template("admin.html", view="dashboard",
                           questions=live, pending=pending,
                           lobbies=sorted_lobbies,
                           new_lobby=new_lobby,
                           active_tab=active_tab)


@app.route("/admin/add", methods=["POST"])
def admin_add():
    if not is_logged_in():
        return redirect(url_for("admin_login"))

    option_a = request.form.get("option_a", "").strip()
    option_b = request.form.get("option_b", "").strip()

    if not option_a or not option_b:
        questions = load_questions()
        live    = [q for q in questions if not q.get("pending", False)]
        pending = [q for q in questions if q.get("pending", False)]
        lobbies = load_lobbies()
        cleanup_lobbies(lobbies)
        save_lobbies(lobbies)
        question_map = {q["id"]: q for q in questions}
        sorted_lobbies = prepare_lobbies_for_admin(lobbies, question_map)
        return render_template("admin.html", view="dashboard",
                               questions=live, pending=pending,
                               lobbies=sorted_lobbies,
                               active_tab="questions",
                               error="Both options are required.")

    questions = load_questions()
    questions.append({
        "id":       next_id(questions),
        "option_a": option_a,
        "option_b": option_b,
        "votes_a":  0,
        "votes_b":  0,
        "pending":  False
    })
    save_questions(questions)
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/add-lobby", methods=["POST"])
def admin_add_lobby():
    if not is_logged_in():
        return redirect(url_for("admin_login"))

    nickname = sanitize_nickname(request.form.get("nickname", ""))
    questions = load_questions()
    live_questions = [q for q in questions if not q.get("pending", False)]
    question_map = {q["id"]: q for q in questions}

    if not nickname:
        error = "A host nickname is required to create a lobby."
    elif not live_questions:
        error = "No live questions are available to seed a lobby."
    else:
        question_ids = [q["id"] for q in live_questions]
        random.shuffle(question_ids)
        question_ids = question_ids[:10]

        lobby_id = generate_lobby_id()
        lobbies = load_lobbies()
        cleanup_lobbies(lobbies)
        lobbies[lobby_id] = {
            "id": lobby_id,
            "question_ids": question_ids,
            "current_index": 0,
            "players": {
                nickname: {"choice": None, "joined_at": time.time(), "last_seen": time.time()}
            },
            "created_at": time.time()
        }
        save_lobbies(lobbies)
        return redirect(url_for("admin_dashboard", new_lobby=lobby_id, tab="lobbies"))

    questions = load_questions()
    live    = [q for q in questions if not q.get("pending", False)]
    pending = [q for q in questions if q.get("pending", False)]
    lobbies  = load_lobbies()
    cleanup_lobbies(lobbies)
    save_lobbies(lobbies)
    sorted_lobbies = prepare_lobbies_for_admin(lobbies, question_map)
    return render_template("admin.html", view="dashboard",
                           questions=live, pending=pending,
                           lobbies=sorted_lobbies,
                           active_tab="lobbies",
                           error=error)


@app.route("/admin/delete-lobby", methods=["POST"])
def admin_delete_lobby():
    if not is_logged_in():
        return redirect(url_for("admin_login"))

    lobby_id = request.form.get("lobby_id")
    lobbies = load_lobbies()
    if lobby_id in lobbies:
        del lobbies[lobby_id]
        save_lobbies(lobbies)

    return redirect(url_for("admin_dashboard", tab="lobbies"))


@app.route("/admin/edit", methods=["POST"])
def admin_edit():
    if not is_logged_in():
        return redirect(url_for("admin_login"))

    question_id = int(request.form.get("question_id"))
    option_a    = request.form.get("option_a", "").strip()
    option_b    = request.form.get("option_b", "").strip()

    try:
        votes_a = int(request.form.get("votes_a", 0))
        votes_b = int(request.form.get("votes_b", 0))
    except ValueError:
        votes_a = 0
        votes_b = 0

    questions = load_questions()
    for question in questions:
        if question["id"] == question_id:
            question["option_a"] = option_a
            question["option_b"] = option_b
            question["votes_a"]  = votes_a
            question["votes_b"]  = votes_b
            break

    save_questions(questions)
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/delete", methods=["POST"])
def admin_delete():
    if not is_logged_in():
        return redirect(url_for("admin_login"))

    question_id = int(request.form.get("question_id"))
    questions   = load_questions()
    questions   = [q for q in questions if q["id"] != question_id]
    save_questions(questions)
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/approve", methods=["POST"])
def admin_approve():
    """
    Approves a pending question — sets pending=False so it
    enters the live question pool.
    """
    if not is_logged_in():
        return redirect(url_for("admin_login"))

    question_id = int(request.form.get("question_id"))
    questions   = load_questions()

    for question in questions:
        if question["id"] == question_id:
            question["pending"] = False
            break

    save_questions(questions)
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/deny", methods=["POST"])
def admin_deny():
    """
    Denies a pending question — deletes it entirely.
    """
    if not is_logged_in():
        return redirect(url_for("admin_login"))

    question_id = int(request.form.get("question_id"))
    questions   = load_questions()
    questions   = [q for q in questions if q["id"] != question_id]
    save_questions(questions)
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/reset-votes", methods=["POST"])
def admin_reset_votes():
    """
    Reset all vote counts and clear the voter log so voting starts fresh.
    """
    if not is_logged_in():
        return redirect(url_for("admin_login"))

    questions = load_questions()
    for question in questions:
        question["votes_a"] = 0
        question["votes_b"] = 0
    save_questions(questions)

    # Clear the IP log so visitors can vote again from a clean state.
    if os.path.exists(IP_LOG_FILE):
        with open(IP_LOG_FILE, "w") as f:
            json.dump({}, f, indent=2)
    # Also clear per-user vote history
    if os.path.exists(USER_VOTES_FILE):
        with open(USER_VOTES_FILE, "w", encoding="utf-8") as f:
            json.dump({}, f, indent=2)

    return redirect(url_for("admin_dashboard"))


@app.route("/admin/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("admin_login"))


# -----------------------------------------------
# RUN THE APP
# -----------------------------------------------

if __name__ == "__main__":
    print("Running on http://0.0.0.0:80")
    serve(app, host='0.0.0.0', port=80, threads=12)
    