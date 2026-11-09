
from flask import Flask

app = Flask(__name__)


@app.route("/")
def strona_glowna():
    return """
    <!DOCTYPE html>
    <html lang="pl">
    <head>
        <meta charset="UTF-8">
        <title>Domowy Bilans</title>
    </head>
    <body>
        <h1>Domowy Bilans</h1>
        <h2>Witaj w swojej aplikacji finansowej!</h2>
        <p>Zarządzaj dochodami, wydatkami i oszczędnościami.</p>
    </body>
    </html>
    """


if __name__ == "__main__":
    app.run(debug=True)

