import sqlite3
import bcrypt
from datetime import datetime, timezone

DATABASE_NAME = "oneiromind.db"

def get_db_connection():
    """Establishes a connection to the SQLite database."""
    conn = sqlite3.connect(DATABASE_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def create_tables():
    """Creates all necessary tables if they don't exist."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            age_range TEXT,
            gender TEXT,
            country TEXT,
            life_stage TEXT
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS chat_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            sender TEXT NOT NULL, -- 'user' or 'bot'
            text TEXT,
            image_data TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES chat_sessions (id)
        )
    ''')
    
    conn.commit()
    conn.close()

def add_user(email, password):
    """Adds a new user to the database."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
        cursor.execute("INSERT INTO users (email, password_hash) VALUES (?, ?)", (email, hashed_password.decode('utf-8')))
        conn.commit()
        new_user_id = cursor.lastrowid
        conn.close()
        return new_user_id
    except sqlite3.IntegrityError:
        conn.close()
        return None

def check_user(email, password):
    """Checks if a user exists and the password is correct."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE email = ?", (email,))
    user = cursor.fetchone()
    conn.close()
    
    if user and bcrypt.checkpw(password.encode('utf-8'), user['password_hash'].encode('utf-8')):
        return dict(user)
    return None

def add_demographics(user_id, age_range, gender, country, life_stage):
    """Adds demographic information for a user."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE users 
        SET age_range = ?, gender = ?, country = ?, life_stage = ?
        WHERE id = ?
    ''', (age_range, gender, country, life_stage, user_id))
    conn.commit()
    conn.close()

def create_chat_session(user_id):
    """Creates a new chat session for a user, saving the timestamp in UTC."""
    conn = get_db_connection()
    cursor = conn.cursor()
    created_at_utc = datetime.now(timezone.utc)
    cursor.execute("INSERT INTO chat_sessions (user_id, created_at) VALUES (?, ?)", (user_id, created_at_utc))
    conn.commit()
    new_session_id = cursor.lastrowid
    conn.close()
    return new_session_id

def add_message_to_session(session_id, sender, text=None, image_data=None):
    """Adds a message to a specific chat session, returning the new message for API responses."""
    conn = get_db_connection()
    cursor = conn.cursor()
    timestamp_utc = datetime.now(timezone.utc)
    cursor.execute(
        "INSERT INTO messages (session_id, sender, text, image_data, timestamp) VALUES (?, ?, ?, ?, ?)",
        (session_id, sender, text, image_data, timestamp_utc)
    )
    new_message_id = cursor.lastrowid
    conn.commit()
    
    # Fetch the newly created message to return it
    cursor.execute("SELECT * FROM messages WHERE id = ?", (new_message_id,))
    new_message = dict(cursor.fetchone())
    conn.close()
    return new_message

def get_user_chat_sessions(user_id):
    """Retrieves all chat sessions for a specific user."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM chat_sessions WHERE user_id = ? ORDER BY created_at DESC", (user_id,))
    sessions = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return sessions

def get_messages_for_session(session_id):
    """Retrieves all messages for a specific session."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM messages WHERE session_id = ? ORDER BY timestamp ASC", (session_id,))
    messages = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return messages

# MODIFIED FUNCTION
def get_user_demographics(user_id):
    """
    Retrieves demographic information for a given user_id from the users table.
    """
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row 
    cursor = conn.cursor()
    
    # Corrected to query the 'users' table instead of a non-existent 'demographics' table
    cursor.execute(
        "SELECT age_range, gender, country, life_stage FROM users WHERE id = ?",
        (user_id,)
    )
    
    demographics = cursor.fetchone()
    conn.close()
    
    if demographics:
        return dict(demographics)
    return None

def is_user_session(user_id, session_id):
    """Checks if a given chat session belongs to the specified user."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT 1 FROM chat_sessions WHERE id = ? AND user_id = ?",
        (session_id, user_id)
    )
    session_exists_for_user = cursor.fetchone()
    conn.close()
    return session_exists_for_user is not None

def delete_chat_session(session_id):
    """Deletes a chat session and all its messages."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
    cursor.execute("DELETE FROM chat_sessions WHERE id = ?", (session_id,))
    conn.commit()
    conn.close()