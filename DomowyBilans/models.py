import datetime as dt

from extensions import db


def money():
    # Numeric(10, 2): kwoty z dokładnością do groszy
    return db.Numeric(10, 2, asdecimal=False)


class Member(db.Model):
    """Domownik."""
    __tablename__ = "member"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(40), unique=True, nullable=False)


class Transaction(db.Model):
    """Zarejestrowany dochód lub wydatek."""
    __tablename__ = "transactions"
    id = db.Column(db.Integer, primary_key=True)
    kind = db.Column(db.String(10), nullable=False)          # income / expense
    amount = db.Column(money(), nullable=False)
    date = db.Column(db.Date, nullable=False, default=dt.date.today)
    category = db.Column(db.String(40), nullable=False)
    description = db.Column(db.String(120), default="")
    nature = db.Column(db.String(10), default="zmienny")      # stały / zmienny
    member_id = db.Column(db.Integer, db.ForeignKey("member.id"))
    member = db.relationship("Member")


class Planned(db.Model):
    """Cykliczny wpływ (źródło dochodu) lub rachunek, powtarzany co miesiąc."""
    __tablename__ = "planned"
    id = db.Column(db.Integer, primary_key=True)
    kind = db.Column(db.String(10), nullable=False)          # income / expense
    name = db.Column(db.String(80), nullable=False)
    amount = db.Column(money(), nullable=False)
    day = db.Column(db.Integer, nullable=False)              # dzień miesiąca (1-31)
    category = db.Column(db.String(40), default="Inne")
    regular = db.Column(db.Boolean, default=True)
    member_id = db.Column(db.Integer, db.ForeignKey("member.id"))
    member = db.relationship("Member")


class Budget(db.Model):
    """Miesięczny limit wydatków dla kategorii."""
    __tablename__ = "budget"
    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(40), unique=True, nullable=False)
    limit = db.Column(money(), nullable=False)


class SavingsGoal(db.Model):
    """Cel oszczędnościowy."""
    __tablename__ = "savings_goal"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(60), nullable=False)
    target = db.Column(money(), nullable=False)
    saved = db.Column(money(), nullable=False, default=0)
    deadline = db.Column(db.Date)
    created = db.Column(db.Date, default=dt.date.today)
