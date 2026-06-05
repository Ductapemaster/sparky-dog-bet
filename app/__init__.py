from flask import Flask
from dotenv import load_dotenv
from datetime import timedelta
import os

load_dotenv()

def create_app():
    app = Flask(__name__)
    app.secret_key = os.environ['SECRET_KEY']
    app.permanent_session_lifetime = timedelta(days=365)

    from . import db
    db.init_db()

    from .routes import bp
    app.register_blueprint(bp)

    return app
