"""Dane przykładowe. Uruchom: python seed.py (czyści bazę i wgrywa dane od nowa)."""
import calendar
import random
from datetime import date

from extensions import db
from models import Budget, Member, Planned, SavingsGoal, Transaction
from services import add_months, clamp_day

VARIABLE = [  # kategoria, liczba zakupów w miesiącu, suma miesięczna, opisy
    ("Żywność", 8, 1700, ["Zakupy spożywcze", "Warzywniak", "Piekarnia"]),
    ("Transport", 4, 450, ["Paliwo", "Bilet miesięczny", "Parking"]),
    ("Rozrywka", 3, 500, ["Kino", "Restauracja", "Streaming"]),
    ("Zdrowie", 2, 200, ["Apteka", "Wizyta kontrolna"]),
    ("Edukacja", 1, 200, ["Kurs online", "Podręczniki"]),
]


def seed(reset=False):
    if reset:
        db.drop_all()
        db.create_all()
    today, rng = date.today(), random.Random(7)
    m = {n: Member(name=n) for n in ("Maria", "Anna", "Wspólne")}
    planned = [
        Planned(kind="income", name="Umowa o prace – Maria", amount=4800, day=10, category="Wynagrodzenie", member=m["Maria"]),
        Planned(kind="income", name="Umowa zlecenie – Anna", amount=3400, day=5, category="Wynagrodzenie", member=m["Anna"], regular=True),
        Planned(kind="income", name="Wynajem pokoju", amount=1200, day=15, category="Inne", member=m["Wspólne"]),
        Planned(kind="expense", name="Czynsz i opłaty", amount=1850, day=5, category="Mieszkanie", member=m["Wspólne"]),
        Planned(kind="expense", name="Prąd i gaz", amount=320, day=18, category="Mieszkanie", member=m["Wspólne"]),
        Planned(kind="expense", name="Internet", amount=70, day=12, category="Mieszkanie", member=m["Wspólne"]),
        Planned(kind="expense", name="Telefony", amount=90, day=20, category="Inne", member=m["Wspólne"]),
        Planned(kind="expense", name="Ubezpieczenie auta", amount=180, day=25, category="Transport", member=m["Maria"]),
    ]
    db.session.add_all(list(m.values()) + planned)

    first_month = add_months(today.replace(day=1), -5)
    db.session.add(Transaction(kind="income", amount=6000, date=first_month, category="Inne",
                               description="Saldo początkowe", nature="zmienny", member=m["Wspólne"]))
    for offset in range(-5, 1):
        first = add_months(today.replace(day=1), offset)
        last_day = calendar.monthrange(first.year, first.month)[1]
        for p in planned:
            d = clamp_day(first.year, first.month, p.day)
            if d <= today:
                db.session.add(Transaction(kind=p.kind, amount=p.amount, date=d, category=p.category,
                                           description=p.name, nature="stały" if p.regular else "zmienny",
                                           member=p.member))
        for cat, count, total, names in VARIABLE:
            for _ in range(count):
                d = first.replace(day=rng.randint(1, last_day))
                if d > today:
                    continue
                db.session.add(Transaction(
                    kind="expense", amount=round(total / count * rng.uniform(0.7, 1.3), 2), date=d,
                    category=cat, description=rng.choice(names), nature="zmienny",
                    member=rng.choice(list(m.values()))))

    db.session.add_all([
        Budget(category="Żywność", limit=1800), Budget(category="Transport", limit=500),
        Budget(category="Rozrywka", limit=400), Budget(category="Zdrowie", limit=300),
        SavingsGoal(name="Wakacje w Grecji", target=8000, saved=3200, deadline=add_months(today, 7)),
        SavingsGoal(name="Fundusz awaryjny", target=30000, saved=6500, deadline=add_months(today, 8)),
    ])
    db.session.commit()


def seed_if_empty():
    if Member.query.count() == 0:
        seed()


if __name__ == "__main__":
    from app import app
    with app.app_context():
        seed(reset=True)
        print("Dane przykładowe wgrane.")
