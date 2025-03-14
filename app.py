import os
import subprocess
from dotenv import load_dotenv

from flask import Flask, render_template, request, flash, redirect, session, g
# from flask_debugtoolbar import DebugToolbarExtension
from sqlalchemy.exc import IntegrityError
from werkzeug.exceptions import Unauthorized

from forms import UserAddForm, LoginForm, MessageForm, CSRFProtectForm, UserEditForm
from models import db, connect_db, User, Message

load_dotenv()

CURR_USER_KEY = "curr_user"

app = Flask(__name__)

app.config['SQLALCHEMY_DATABASE_URI'] = os.environ['DATABASE_URL']
app.config['SQLALCHEMY_ECHO'] = False
# app.config['DEBUG_TB_INTERCEPT_REDIRECTS'] = False
app.config['SECRET_KEY'] = os.environ['SECRET_KEY']
# toolbar = DebugToolbarExtension(app)

connect_db(app)


##############################################################################
# User signup/login/logout


@app.before_request
def add_user_to_g():
    """If we're logged in, add curr user to Flask global."""
    if CURR_USER_KEY in session:
        g.user = User.query.get(session[CURR_USER_KEY])

    else:
        g.user = None


@app.before_request
def add_csrf_form_to_g():
    """Adds csrf protection form to Flask global"""

    g.csrf_form = CSRFProtectForm()


def do_login(user):
    """Log in user."""

    session[CURR_USER_KEY] = user.id


def do_logout():
    """Log out user."""

    if CURR_USER_KEY in session:
        del session[CURR_USER_KEY]


@app.route('/signup', methods=["GET", "POST"])
def signup():
    """Handle user signup.

    Create new user and add to DB. Redirect to home page.

    If form not valid, present form.

    If the there already is a user with that username: flash message
    and re-present form.
    """

    do_logout()

    form = UserAddForm()

    if form.validate_on_submit():
        try:
            user = User.signup(
                username=form.username.data,
                password=form.password.data,
                email=form.email.data,
                image_url=form.image_url.data or User.image_url.default.arg,
            )

            db.session.add(user)
            db.session.commit()

        except IntegrityError:
            db.session.rollback()

            flash("Username or email already taken", 'danger')
            return render_template('users/signup.html', form=form)

        do_login(user)

        return redirect("/")

    else:
        return render_template('users/signup.html', form=form)


@app.route('/login', methods=["GET", "POST"])
def login():
    """Handle user login and redirect to homepage on success."""

    form = LoginForm()

    if form.validate_on_submit():
        user = User.authenticate(
            form.username.data,
            form.password.data,
        )

        if user:
            do_login(user)

            flash(f"Hello, {user.username}!", "success")
            return redirect("/")

        flash("Invalid credentials.", 'danger')

    return render_template('users/login.html', form=form)


@app.post('/logout')
def logout():
    """Handle logout of user and redirect to homepage."""

    if not g.user:
        flash("Access unauthorized!", "danger")
        return redirect("/")

    if g.csrf_form.validate_on_submit():
        do_logout()

        flash("Succesfully logged out")
        return redirect('/login')

    else:
        raise Unauthorized()


##############################################################################
# General user routes:

@app.get('/users')
def list_users():
    """Page with listing of users.

    Can take a 'q' param in querystring to search by that username.
    """

    if not g.user:
        flash("Access unauthorized!", "danger")
        return redirect("/")

    search = request.args.get('q')

    if not search:
        users = User.query.all()
    else:
        users = User.query.filter(User.username.like(f"%{search}%")).all()

    return render_template('users/index.html', users=users)


@app.get('/users/<int:user_id>')
def show_user(user_id):
    """Show user profile."""
    if not g.user:
        flash("Access unauthorized!", "danger")
        return redirect("/")

    user = User.query.get_or_404(user_id)
    return render_template('users/show.html', user=user)


@app.get('/users/<int:user_id>/following')
def show_following(user_id):
    """Show list of people this user is following."""

    if not g.user:
        flash("Access unauthorized!", "danger")
        return redirect("/")

    user = User.query.get_or_404(user_id)
    return render_template('users/following.html', user=user)


@app.get('/users/<int:user_id>/followers')
def show_followers(user_id):
    """Show list of followers of this user."""

    if not g.user:
        flash("Access unauthorized!", "danger")
        return redirect("/")

    user = User.query.get_or_404(user_id)
    return render_template('users/followers.html', user=user)


@app.post('/users/follow/<int:follow_id>')
def start_following(follow_id):
    """Add a follow for the currently-logged-in user.

    Redirect to following page for the current for the current user.
    """

    if not g.user:
        flash("Access unauthorized!", "danger")
        return redirect("/")

    if g.user.id == follow_id:
        flash("You cannot follow yourself!", "danger")
        return redirect('/')

    if g.csrf_form.validate_on_submit():
        followed_user = User.query.get_or_404(follow_id)

        if g.user.is_following(followed_user):
            flash("You are already following that person!")

        else:
            g.user.following.append(followed_user)
            db.session.commit()

        return redirect(f"/users/{g.user.id}/following")

    else:
        raise Unauthorized()


@app.post('/users/stop-following/<int:follow_id>')
def stop_following(follow_id):
    """Have currently-logged-in-user stop following this user.

    Redirect to following page for the current for the current user.
    """

    if not g.user:
        flash("Access unauthorized!", "danger")
        return redirect("/")

    if g.csrf_form.validate_on_submit():
        followed_user = User.query.get_or_404(follow_id)

        if g.user.is_following(followed_user):
            g.user.following.remove(followed_user)
            db.session.commit()

        else:
            flash("You cannot unfollow someone that you are not following")

        return redirect(f"/users/{g.user.id}/following")

    else:
        raise Unauthorized()


@app.route('/users/profile', methods=["GET", "POST"])
def edit_profile():
    """Update profile for current user."""

    if not g.user:
        flash("Access unauthorized!", "danger")
        return redirect("/")

    form = UserEditForm(obj=g.user)

    if form.validate_on_submit():
        psw = form.password.data

        # user is either a user instance or False
        user = User.authenticate(g.user.username, psw)

        if not user:
            flash("Incorrect password", 'danger')
            return render_template('users/edit.html', form=form)

        try:
            user.username = form.username.data
            user.email = form.email.data
            user.image_url = form.image_url.data or User.image_url.default.arg
            user.header_image_url = (form.header_image_url.data
                                     or User.header_image_url.default.arg)
            user.bio = form.bio.data

            db.session.commit()

        except IntegrityError:
            db.session.rollback()

            flash("Username or email already taken", 'danger')
            return render_template('users/edit.html', form=form)

        else:
            return redirect(f'/users/{user.id}')

    else:
        return render_template('users/edit.html', form=form)


@app.post('/users/delete')
def delete_user():
    """Delete user.

    Redirect to signup page.
    """

    if not g.user:
        flash("Access unauthorized!", "danger")
        return redirect("/")

    if g.csrf_form.validate_on_submit():
        do_logout()

        Message.query.filter_by(user_id=g.user.id).delete()

        db.session.delete(g.user)
        db.session.commit()

        return redirect("/signup")

    else:
        raise Unauthorized()


##############################################################################
# Messages routes:

@app.route('/messages/new', methods=["GET", "POST"])
def add_message():
    """Add a message:

    Show form if GET. If valid, update message and redirect to user page.
    """

    if not g.user:
        flash("Access unauthorized!", "danger")
        return redirect("/")

    form = MessageForm()

    if form.validate_on_submit():
        msg = Message(text=form.text.data)
        g.user.messages.append(msg)
        db.session.commit()

        return redirect(f"/users/{g.user.id}")

    return render_template('messages/create.html', form=form)


@app.get('/messages/<int:message_id>')
def show_message(message_id):
    """Show a message."""

    if not g.user:
        flash("Access unauthorized!", "danger")
        return redirect("/")

    msg = Message.query.get_or_404(message_id)
    return render_template('messages/show.html', message=msg)


@app.post('/messages/<int:message_id>/delete')
def delete_message(message_id):
    """Delete a message.

    Check that this message was written by the current user.
    Redirect to user page on success.
    """

    msg = Message.query.get_or_404(message_id)

    if not g.user:
        flash("Access unauthorized!", "danger")
        return redirect("/")

    if msg.user_id != g.user.id:
        raise Unauthorized()

    if g.csrf_form.validate_on_submit():
        db.session.delete(msg)
        db.session.commit()

        flash('Message deleted!')
        return redirect(f"/users/{g.user.id}")

    else:
        raise Unauthorized()

##############################################################################
# Likes routes:


@app.post('/messages/<int:message_id>/like-toggle')
def toggle_message_like(message_id):
    """Like a message"""

    if not g.user:
        flash("Access unauthorized!", "danger")
        return redirect("/")

    msg = Message.query.get_or_404(message_id)

    if g.csrf_form.validate_on_submit():

        request_url = request.form.get('origin_url', '/')

        if g.user.id == msg.user.id:
            flash('Cannot like your own messages!', 'danger')
            return redirect(request_url)

        if g.user.has_liked(msg):
            g.user.likes.remove(msg)
        else:
            g.user.likes.append(msg)

        db.session.commit()
        return redirect(request_url)

    else:
        raise Unauthorized()


@app.get('/users/<int:user_id>/likes')
def get_and_display_user_likes(user_id):
    """Displays list of liked messages"""

    if not g.user:
        flash("Access unauthorized!", "danger")
        return redirect("/")

    user = User.query.get_or_404(user_id)
    return render_template('users/show_likes.html', user=user)


############################
# Homepage and error pages #
############################

@app.get('/')
def homepage():
    """Show homepage:

    - anon users: no messages
    - logged in: 100 most recent messages of self & followed_users
    """

    if g.user:
        self_plus_is_following = g.user.following.copy()
        self_plus_is_following.append(g.user)

        ids = [u.id for u in self_plus_is_following]

        messages = (Message
                    .query
                    .filter(Message.user_id.in_(ids))
                    .order_by(Message.timestamp.desc())
                    .limit(100)
                    .all())

        return render_template('home.html', messages=messages)

    else:
        return render_template('home-anon.html')


@app.errorhandler(Unauthorized)
def page_unauthorized(e):
    """Shows Unauthorized page."""

    return render_template('unauthorized.html'), 401


@app.errorhandler(404)
def page_not_found(e):
    """Shows 404 NOT FOUND page."""

    return render_template('404.html'), 404


@app.after_request
def add_header(response):
    """Add non-caching headers on every request."""

    # https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Cache-Control
    response.cache_control.no_store = True
    return response


#################
# Database init #
#################


# Ideally we would do this in the render shell, but that isn't accessible in
# free tier
# Initialize DB Route (Creates tables & seeds database)
@app.route("/init-db")
def init_db():
    try:
        # Run the seed script
        subprocess.run(["python", "seed.py"], check=True)

        return "Database initialized and seeded successfully!"
    except Exception as e:
        return f"Error initializing DB: {str(e)}"