"""Aplikacja Domowy Bilans."""
import csv
import io
from datetime import date

from flask import Flask, flash, make_response, redirect, render_template, request, url_for

from config import Config
from extensions import db
from models import Budget, Member, Planned, SavingsGoal, Transaction
import services

app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)


@app.template_filter("pln")
def pln(value):
    return services.pln(value)


def form_amount(field):
    return services.parse_amount(request.form.get(field))


def categories():
    return services.CATEGORIES


@app.route("/")
def index():
    return render_template("index.html", summary=services.summary(), forecast=services.forecast(),
                           chart=services.monthly_series(), events=services.upcoming_events(),
                           transactions=services.recent_transactions())


@app.route("/transakcje", methods=["GET", "POST"])
def transakcje():
    if request.method == "POST":
        amount, tx_date = form_amount("amount"), services.parse_date(request.form.get("date"))
        kind, category = request.form.get("kind"), request.form.get("category")
        member = Member.query.filter_by(name=request.form.get("member", "")).first()
        if not amount or not tx_date or kind not in ("income", "expense") or category not in categories() or not member:
            flash("Sprawdź kwotę, datę, kategorię i domownika.", "error")
        else:
            tx = Transaction(kind=kind, amount=amount, date=tx_date, category=category,
                             description=request.form.get("description", "").strip()[:120],
                             nature=request.form.get("nature") if request.form.get("nature") in ("stały", "zmienny") else "zmienny",
                             member=member)
            db.session.add(tx)
            db.session.commit()
            flash("Transakcja została zapisana.", "success")
            return redirect(url_for("transakcje"))
    query = services.filter_transactions(request.args)
    if request.args.get("eksport") == "csv":
        output = io.StringIO()
        writer = csv.writer(output, delimiter=";")
        writer.writerow(["Data", "Rodzaj", "Opis", "Kategoria", "Domownik", "Regularność", "Kwota (zł)"])
        for tx in query.all():
            writer.writerow([tx.date.isoformat(), "Dochód" if tx.kind == "income" else "Wydatek", tx.description,
                             tx.category, tx.member.name if tx.member else "", tx.nature, f"{tx.amount:.2f}".replace(".", ",")])
        response = make_response("\ufeff" + output.getvalue())
        response.headers["Content-Type"] = "text/csv; charset=utf-8"
        response.headers["Content-Disposition"] = "attachment; filename=transakcje.csv"
        return response
    members = [m.name for m in Member.query.order_by(Member.name)]
    return render_template("transakcje.html", categories=categories(), members=members,
                           transactions=[services.row(t) for t in query.all()], today=date.today().isoformat(),
                           fixed_items=services.regular_items())


@app.route("/transakcje/<int:tx_id>/usun", methods=["POST"])
def usun_transakcje(tx_id):
    tx = db.session.get(Transaction, tx_id)
    if tx:
        db.session.delete(tx)
        db.session.commit()
        flash("Transakcja została usunięta.", "success")
    return redirect(url_for("transakcje", **request.args))


@app.route("/transakcje/stale/<int:item_id>/usun", methods=["POST"])
def usun_stala_pozycje(item_id):
    item = db.session.get(Planned, item_id)
    if item and item.regular:
        db.session.delete(item)
        db.session.commit()
        flash("Pozycja została usunięta z planu. Zapisane transakcje pozostają w historii.", "success")
    return redirect(url_for("transakcje"))


@app.route("/budzet", methods=["GET", "POST"])
def budzet():
    if request.method == "POST":
        kind = request.form.get("form")
        if kind == "budget":
            category, amount = request.form.get("category"), form_amount("limit")
            if category not in services.EXPENSE_CATEGORIES or not amount:
                flash("Wybierz kategorię wydatku i poprawny limit.", "error")
            else:
                item = Budget.query.filter_by(category=category).first()
                if item:
                    item.limit = amount
                else:
                    db.session.add(Budget(category=category, limit=amount))
                db.session.commit()
                flash("Limit został zapisany.", "success")
                return redirect(url_for("budzet"))
        elif kind == "goal":
            name, target = request.form.get("name", "").strip(), form_amount("target")
            deadline_raw = request.form.get("deadline", "")
            deadline = services.parse_date(deadline_raw) if deadline_raw else None
            if not name or not target or (deadline_raw and not deadline):
                flash("Podaj nazwę, poprawną kwotę i prawidłowy termin celu.", "error")
            else:
                db.session.add(SavingsGoal(name=name[:60], target=target, deadline=deadline))
                db.session.commit()
                flash("Cel został dodany.", "success")
                return redirect(url_for("budzet"))
        elif kind == "deposit":
            amount = form_amount("amount")
            if not amount:
                flash("Podaj poprawną kwotę wpłaty.", "error")
            else:
                error = services.deposit(request.form.get("goal_id", type=int), amount)
                flash(error or "Wpłata została dodana do celu.", "error" if error else "success")
                if not error:
                    return redirect(url_for("budzet"))
    overview = services.budget_overview()
    goals = services.goals_overview()
    return render_template("budzet.html", categories=services.EXPENSE_CATEGORIES,
                           budgets=overview["rows"], potential=overview["potential"],
                           goals=goals["goals"], tips=goals["tips"], today=date.today().isoformat())


@app.route("/budzet/limity/<int:budget_id>/usun", methods=["POST"])
def usun_limit(budget_id):
    item = db.session.get(Budget, budget_id)
    if item:
        db.session.delete(item)
        db.session.commit()
        flash("Limit został usunięty.", "success")
    return redirect(url_for("budzet"))


@app.route("/budzet/cele/<int:goal_id>/usun", methods=["POST"])
def usun_cel(goal_id):
    item = db.session.get(SavingsGoal, goal_id)
    if item:
        db.session.delete(item)
        db.session.commit()
        flash("Cel został usunięty.", "success")
    return redirect(url_for("budzet"))


@app.route("/symulacje", methods=["GET", "POST"])
def symulacje():
    sources = Planned.query.filter_by(kind="income").order_by(Planned.name).all()
    result = None
    if request.method == "POST":
        scenario = request.form.get("scenario")
        duration = request.form.get("duration", "").strip()
        horizon = request.form.get("horizon", type=int) or 12
        amount = form_amount("amount") or 0
        source_id = request.form.get("source", type=int) if scenario == "income_loss" else None
        loss_months = None if not duration else int(duration) if duration.isdigit() else 0
        if scenario not in ("income_loss", "expense") or not 1 <= horizon <= 24 or (
                scenario == "income_loss" and loss_months is not None and not 1 <= loss_months <= 24):
            flash("Wybierz prawidłowy scenariusz i okres od 1 do 24 miesięcy.", "error")
        elif scenario == "income_loss" and not any(s.id == source_id for s in sources):
            flash("Wybierz źródło dochodu do symulacji.", "error")
        elif scenario == "expense" and amount <= 0:
            flash("Podaj kwotę niespodziewanego wydatku.", "error")
        else:
            result = services.simulate(source_id, loss_months if scenario == "income_loss" else 0,
                                       amount if scenario == "expense" else 0, horizon)
    return render_template("symulacje.html", sources=sources, result=result)


with app.app_context():
    db.create_all()
    from seed import seed_if_empty
    seed_if_empty()


if __name__ == "__main__":
    app.run(debug=True)
