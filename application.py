import os
from datetime import datetime

from cs50 import SQL
from flask import Flask, flash, jsonify, redirect, render_template, request, session
from flask_session import Session
from tempfile import mkdtemp
from werkzeug.exceptions import default_exceptions, HTTPException, InternalServerError
from werkzeug.security import check_password_hash, generate_password_hash

from helpers import apology, login_required, lookup, usd

# Configure application
app = Flask(__name__)

# Ensure templates are auto-reloaded
app.config["TEMPLATES_AUTO_RELOAD"] = True

# Ensure responses aren't cached
@app.after_request
def after_request(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response

# Custom filter
app.jinja_env.filters["usd"] = usd

# Configure session to use filesystem (instead of signed cookies)
app.config["SESSION_FILE_DIR"] = mkdtemp()
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Configure CS50 Library to use SQLite database
db = SQL("sqlite:///finance.db")

# Make sure API key is set
if not os.environ.get("API_KEY"):
    raise RuntimeError("API_KEY not set")


@app.route("/", methods=["GET", "POST"])
@login_required
def index():
    """Show portfolio of stocks"""
    if request.method == "POST":
        cashAdded = request.form.get("added")
        db.execute("UPDATE users SET cash=cash+:cashAdded WHERE id = :userId", cashAdded=cashAdded, userId=session["user_id"])

    owned = db.execute("SELECT * FROM owned WHERE userId = :userId", userId=session["user_id"])

    userStocks = []
    cash = db.execute("SELECT cash FROM users WHERE id = :userId", userId=session["user_id"])
    totalValue = cash[0]["cash"]

    for row in owned:
        quoted = lookup(row["symbol"])
        row["price"] = usd(float(quoted["price"]))
        row["total"] = float(quoted["price"])*row["shares"]
        totalValue += row["total"]

        row["total"] = usd(float(row["total"]))
        row["name"] = quoted["name"]

        userStocks.append(row)

    return render_template("index.html", owned=userStocks, totalValue=usd(totalValue), cash=usd(cash[0]["cash"]))


@app.route("/buy", methods=["GET", "POST"])
@login_required
def buy():
    """Buy shares of stock"""
    if request.method == "POST":

        bought = lookup(request.form.get("symbol"))

        if not bought:
            return render_template("buy.html", missing=True)

        shares = int(request.form.get("shares"))

        if shares < 1:
            return apology("You must buy a positive number of shares", 403)

        price = bought["price"] * shares
        row = db.execute("SELECT cash FROM users WHERE id=:userId", userId=session["user_id"])

        if row[0]["cash"] < price:
            return apology("You do not have enough cash", 404)

        db.execute("INSERT INTO transactions (userId, symbol, shares, priceAtTransaction, transactionType, timeOfTransaction) VALUES (:userId, :symbol, :shares, :priceAtTransaction, :transactionType, :timeOfTransaction)",
                   userId=session["user_id"], symbol=bought["symbol"], shares=shares, priceAtTransaction=bought["price"], transactionType="Purchase", timeOfTransaction=datetime.now())

        db.execute("UPDATE users SET cash=cash - :price WHERE id=:userId", price=price, userId=session["user_id"])

        owned = db.execute("SELECT * FROM owned WHERE userId=:userId AND symbol=:symbol", userId=session["user_id"], symbol=bought["symbol"])

        if not owned:
            db.execute("INSERT INTO owned (userId, symbol, shares) VALUES (:userId, :symbol, :shares)", userId=session["user_id"], symbol=bought["symbol"], shares=shares)
        else:
            db.execute("UPDATE owned SET shares=shares + :newShares WHERE userId=:userId AND symbol=:symbol", userId=session["user_id"], newShares=shares, symbol=bought["symbol"])

        return redirect("/")

    else:
        return render_template("buy.html")


@app.route("/history")
@login_required
def history():
    """Show history of transactions"""
    transactions = db.execute("SELECT * FROM transactions WHERE userId = :userId ORDER BY timeOfTransaction DESC", userId = session["user_id"])

    return render_template("history.html", transactions=transactions)


@app.route("/login", methods=["GET", "POST"])
def login():
    """Log user in"""

    # Forget any user_id
    session.clear()

    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":

        # Ensure username was submitted
        if not request.form.get("username"):
            return apology("must provide username", 403)

        # Ensure password was submitted
        elif not request.form.get("password"):
            return apology("must provide password", 403)

        # Query database for username
        rows = db.execute("SELECT * FROM users WHERE username = :username",
                          username=request.form.get("username"))

        # Ensure username exists and password is correct
        if len(rows) != 1 or not check_password_hash(rows[0]["hash"], request.form.get("password")):
            return apology("invalid username and/or password", 403)

        # Remember which user has logged in
        session["user_id"] = rows[0]["id"]

        # Redirect user to home page
        return redirect("/")

    # User reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("login.html")


@app.route("/logout")
def logout():
    """Log user out"""

    # Forget any user_id
    session.clear()

    # Redirect user to login form
    return redirect("/")


@app.route("/quote", methods=["GET", "POST"])
@login_required
def quote():
    """Get stock quote."""
    if request.method == "POST":

        quoted = lookup(request.form.get("symbol"))

        if not quoted:
            return render_template("quote.html", missing=True)

        quoted["price"] = usd(quoted["price"])

        return render_template("quoted.html", quoted=quoted)

    else:
        return render_template("quote.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    """Register user"""
    session.clear()

    if request.method == "POST":

        username=request.form.get("username")
        password=request.form.get("password")
        confirmation=request.form.get("confirmation")

        if not username:
            return apology("must provide username", 403)

        elif not password:
            return apology("must provide password", 403)

        elif not confirmation or password != confirmation:
            return apology("must confirm password", 403)

        rows = db.execute("SELECT * FROM users WHERE username = :username",
                          username=username)

        if len(rows) != 0:
            return apology("Username already exists", 403)

        session["user_id"] = db.execute("INSERT INTO users (username, hash) VALUES (:username, :hashed)",
                                        username=username, hashed=generate_password_hash(password))

        return redirect("/")

    else:
        return render_template("register.html")


@app.route("/sell", methods=["GET", "POST"])
@login_required
def sell():
    """Sell shares of stock"""
    if request.method == "POST":

        symbol = request.form.get("symbol")
        sold = lookup(symbol)

        if not sold:
            return apology("Please select a stock to sell", 404)

        shares = int(request.form.get("shares"))

        ownedShares = db.execute("SELECT shares FROM owned WHERE userId = :userId AND symbol = :symbol", userId=session["user_id"], symbol=symbol)[0]["shares"]

        if shares > ownedShares or shares < 1:
            return apology("Insufficient shares to sell", 404)

        sellPrice = sold["price"]*shares

        db.execute("INSERT INTO transactions (userId, symbol, shares, priceAtTransaction, transactionType, timeOfTransaction) VALUES (:userId, :symbol, :shares, :priceAtTransaction, :transactionType, :timeOfTransaction)",
                   userId=session["user_id"], symbol=sold["symbol"], shares=shares, priceAtTransaction=sold["price"], transactionType="Sale", timeOfTransaction=datetime.now())

        db.execute("UPDATE users SET cash=cash + :sellPrice WHERE id=:userId", sellPrice=sellPrice, userId=session["user_id"])


        if shares == ownedShares:
            db.execute("DELETE FROM owned WHERE userId=:userId AND symbol=:symbol", userId=session["user_id"], symbol=sold["symbol"])
        else:
            db.execute("UPDATE owned SET shares=shares - :soldShares WHERE userId=:userId AND symbol=:symbol", userId=session["user_id"], soldShares=shares, symbol=sold["symbol"])

        return redirect("/")

    else:
        owned = db.execute("SELECT symbol FROM owned WHERE userId = :userId", userId=session["user_id"])
        return render_template("sell.html", owned=owned)



def errorhandler(e):
    """Handle error"""
    if not isinstance(e, HTTPException):
        e = InternalServerError()
    return apology(e.name, e.code)


# Listen for errors
for code in default_exceptions:
    app.errorhandler(code)(errorhandler)
