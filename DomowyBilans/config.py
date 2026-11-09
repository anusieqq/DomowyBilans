
import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

class Config:
    SECRET_KEY = "domowy-bilans-klucz-123"
    SQLALCHEMY_DATABASE_URI = "sqlite:///" + os.path.join(BASE_DIR, "domowy_bilans.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
