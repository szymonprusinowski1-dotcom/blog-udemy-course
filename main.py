import os
from datetime import date
from flask import Flask, abort, render_template, redirect, url_for, flash
from flask_bootstrap import Bootstrap5
from flask_ckeditor import CKEditor
from flask_login import login_user, LoginManager, current_user, logout_user
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from forms import CreatePostForm, RegisterForm, LoginForm, CommentForm
from werkzeug.utils import secure_filename
import uuid
from itsdangerous import URLSafeTimedSerializer
import resend
from resend.exceptions import ResendError
from dotenv import load_dotenv
from models import db, BlogPost, User, Comment

load_dotenv()

RESEND_API_KEY = os.environ.get('RESEND_API_KEY')
resend.api_key = RESEND_API_KEY

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY')
ckeditor = CKEditor(app)
Bootstrap5(app)
login_manager = LoginManager()
login_manager.init_app(app)
serializer = URLSafeTimedSerializer(app.config['SECRET_KEY'])

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///posts.db'
db.init_app(app)


with app.app_context():
    db.create_all()


@login_manager.user_loader
def load_user(user_id):
    return db.get_or_404(User, user_id)

def admin_only(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or current_user.id != 1:
            return abort(403)
        return function(*args, **kwargs)
    return wrapper


@app.route('/register', methods=['GET', 'POST'])
def register():
    form = RegisterForm()
    user_email = form.email.data
    if form.validate_on_submit():
        existing_user = db.session.execute(db.select(User).where(User.email == user_email)).scalar()

        if existing_user:
            flash("User already exists!")
            return redirect(url_for('login'))

        else:
            photo = form.avatar.data
            if photo:
                filename = secure_filename(photo.filename)
                name, extension = os.path.splitext(filename)
                uuid_name = str(uuid.uuid4())
                filename = uuid_name + extension.lower()
                photo.save(os.path.join(app.static_folder, 'avatars', filename))
            else:
                filename = None

            new_user = User(
                email=form.email.data,
                password=generate_password_hash(form.password.data, method='pbkdf2:sha256', salt_length=8),
                name=form.name.data,
                avatar_url=filename,
            )
            db.session.add(new_user)
            db.session.commit()
            token = serializer.dumps(
                {"user_id": new_user.id},
                salt="email-verification"
            )

            verification_url = url_for(
                "verified",
                token=token,
                _external=True
            )

            params: resend.Emails.SendParams = {
                "from": "SzymonBlog <onboarding@resend.dev>",
                "to": [f"{new_user.email}"],
                "subject": "SzymonBlog verification link",
                "html": f"""
                    <strong>Click this link to verify your account:</strong>
                    <a href="{verification_url}">Verify account</a>
                """
            }

            try:
                email = resend.Emails.send(params)
                print(email)
            except ResendError as error:
                print(error)

            login_user(new_user)

            return redirect(url_for('verification'))
    return render_template("register.html", form=form)


@app.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()
    user_email = form.email.data
    user_password = form.password.data

    result = db.session.execute(db.select(User).where(User.email == user_email))
    user = result.scalar()

    if form.validate_on_submit():
        if not user:
            flash("The email does not exist, please try again.")
            return redirect(url_for('login'))
        if not check_password_hash(user.password, user_password):
            flash("Wrong password, please try again.")
            return redirect(url_for('login'))
        else:
            login_user(user)
            return redirect(url_for('get_all_posts'))
    return render_template("login.html", form=form)


@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('get_all_posts'))


@app.route('/')
def get_all_posts():
    result = db.session.execute(db.select(BlogPost))
    posts = result.scalars().all()
    return render_template("index.html", all_posts=posts)


@app.route("/post/<int:post_id>", methods=['GET', 'POST'])
def show_post(post_id):
    form = CommentForm()
    requested_post = db.get_or_404(BlogPost, post_id)
    if form.validate_on_submit():
        if not current_user.is_authenticated:
            flash("You need to login or register to comment.")
            return redirect(url_for("login"))

        new_comment = Comment(
            text=form.body.data,
            comment_author=current_user,
            comment_post=requested_post
        )
        db.session.add(new_comment)
        db.session.commit()
    return render_template("post.html", post=requested_post, current_user=current_user, form=form)


@app.route("/new-post", methods=["GET", "POST"])
@admin_only
def add_new_post():
    form = CreatePostForm()
    if form.validate_on_submit():
        new_post = BlogPost(
            title=form.title.data,
            subtitle=form.subtitle.data,
            body=form.body.data,
            img_url=form.img_url.data,
            author=current_user,
            date=date.today().strftime("%B %d, %Y")
        )
        db.session.add(new_post)
        db.session.commit()
        return redirect(url_for("get_all_posts"))
    return render_template("make-post.html", form=form)


@app.route("/edit-post/<int:post_id>", methods=["GET", "POST"])
@admin_only
def edit_post(post_id):
    post = db.get_or_404(BlogPost, post_id)
    edit_form = CreatePostForm(
        title=post.title,
        subtitle=post.subtitle,
        img_url=post.img_url,
        author=post.author,
        body=post.body
    )
    if edit_form.validate_on_submit():
        post.title = edit_form.title.data
        post.subtitle = edit_form.subtitle.data
        post.img_url = edit_form.img_url.data
        post.author = current_user
        post.body = edit_form.body.data
        db.session.commit()
        return redirect(url_for("show_post", post_id=post.id))
    return render_template("make-post.html", form=edit_form, is_edit=True)


@app.route("/delete/<int:post_id>")
@admin_only
def delete_post(post_id):
    post_to_delete = db.get_or_404(BlogPost, post_id)
    db.session.delete(post_to_delete)
    db.session.commit()
    return redirect(url_for('get_all_posts'))


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/contact")
def contact():
    return render_template("contact.html")


@app.route("/verification")
def verification():
    return render_template("verification.html")


@app.route("/verified/<token>")
def verified(token):
    data = serializer.loads(
        token,
        salt="email-verification",
        max_age=3600
    )
    user_id = data["user_id"]
    user = db.session.get(User, user_id)
    user.is_verified = True
    db.session.commit()
    return render_template("verified.html")


if __name__ == "__main__":
    app.run(debug=True, port=5002)
