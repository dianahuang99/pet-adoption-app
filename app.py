from locale import currency
import os

from flask import Flask, render_template, request, flash, redirect, session, g, abort
from flask_debugtoolbar import DebugToolbarExtension
from numpy import nanmax
from sqlalchemy.exc import IntegrityError
from sympy import preview
from time import sleep

from forms import UserAddForm, LoginForm, MessageForm, EditUserForm
from models import db, connect_db, User, Organization, SavedOrgs, Animal, SavedAnimals
import requests


CURR_USER_KEY = "curr_user"

app = Flask(__name__)

# Get DB_URI from environ variable (useful for production/testing) or,
# if not set there, use development local db.
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "DATABASE_URL", "postgresql:///adopt_a_pet"
)

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SQLALCHEMY_ECHO"] = False
app.config["DEBUG_TB_INTERCEPT_REDIRECTS"] = False
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "it's a secret")
toolbar = DebugToolbarExtension(app)

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


def do_login(user):
    """Log in user."""

    session[CURR_USER_KEY] = user.id


def do_logout():
    """Logout user."""

    if CURR_USER_KEY in session:
        del session[CURR_USER_KEY]


@app.route("/signup", methods=["GET", "POST"])
def signup():
    """Handle user signup.

    Create new user and add to DB. Redirect to home page.

    If form not valid, present form.

    If the there already is a user with that username: flash message
    and re-present form.
    """

    form = UserAddForm()

    if form.validate_on_submit():
        try:
            user = User.signup(
                username=form.username.data,
                password=form.password.data,
                email=form.email.data,
            )
            db.session.commit()

        except IntegrityError:
            flash("Username already taken", "danger")
            return render_template("users/signup.html", form=form)

        do_login(user)

        return redirect("/")

    else:
        return render_template("users/signup.html", form=form)


token_request = {
    "grant_type": "client_credentials",
    "client_id": "LCoVVX137txFqzFIgK9dfOLACO3fPyUxgxGkeqG0JcC5pzOzav",
    "client_secret": "3IziiMSRjQiLrniOuKOKXi1VPQ8zRd7hqxEU69eh",
}


@app.route("/login", methods=["GET", "POST"])
def login():
    """Handle user login."""

    form = LoginForm()

    if form.validate_on_submit():
        user = User.authenticate(form.username.data, form.password.data)

        if user:
            do_login(user)
            flash(f"Hello, {user.username}!", "success")
            res = requests.post(
                "https://api.petfinder.com/v2/oauth2/token", json=token_request
            )
            session["token"] = res.json()["access_token"]
            return redirect("/")

        flash("Invalid credentials.", "danger")

    return render_template("users/login.html", form=form)


@app.route("/logout")
def logout():
    """Handle logout of user."""
    if CURR_USER_KEY not in session:
        flash("You are already logged out!")
        return redirect("/")
    session.pop(CURR_USER_KEY)
    flash("Logged out successfully", "danger")
    return redirect("/login")


##############################################################################
# General user routes:


@app.route("/users")
def list_users():
    """Page with listing of users.

    Can take a 'q' param in querystring to search by that username.
    """

    search = request.args.get("q")

    if not search:
        users = User.query.all()
    else:
        users = User.query.filter(User.username.like(f"%{search}%")).all()

    return render_template("users/index.html", users=users)


@app.route("/users/<int:user_id>")
def users_show(user_id):
    """Show user profile."""

    user = User.query.get_or_404(user_id)

    
    return render_template("users/show.html", user=user)



@app.route("/users/<int:user_id>/followers")
def users_followers(user_id):
    """Show list of followers of this user."""

    if not g.user:
        flash("Access unauthorized.", "danger")
        return redirect("/")

    user = User.query.get_or_404(user_id)
    return render_template("users/followers.html", user=user)


@app.route("/users/follow/<int:follow_id>", methods=["POST"])
def add_follow(follow_id):
    """Add a follow for the currently-logged-in user."""

    if not g.user:
        flash("Access unauthorized.", "danger")
        return redirect("/")

    followed_user = User.query.get_or_404(follow_id)
    g.user.following.append(followed_user)
    db.session.commit()

    return redirect(f"/users/{g.user.id}/following")


@app.route("/users/stop-following/<int:follow_id>", methods=["POST"])
def stop_following(follow_id):
    """Have currently-logged-in-user stop following this user."""

    if not g.user:
        flash("Access unauthorized.", "danger")
        return redirect("/")

    followed_user = User.query.get(follow_id)
    g.user.following.remove(followed_user)
    db.session.commit()

    return redirect(f"/users/{g.user.id}/following")


@app.route("/users/profile", methods=["GET", "POST"])
def profile():
    """Update profile for current user."""
    curr_user = User.query.get(session[CURR_USER_KEY])
    form = EditUserForm(obj=curr_user)
    if form.validate_on_submit():
        user = User.authenticate(curr_user.username, form.password.data)

        if user:
            user.username = form.username.data
            user.email = form.email.data
            db.session.commit()
            flash("Your profile was edited", "success")
            return redirect(f"/users/{session[CURR_USER_KEY]}")

        flash("Invalid credentials.", "danger")
        return redirect("/")
    return render_template("users/edit.html", form=form)


@app.route("/users/delete", methods=["POST"])
def delete_user():
    """Delete user."""

    if not g.user:
        flash("Access unauthorized.", "danger")
        return redirect("/")

    do_logout()

    db.session.delete(g.user)
    db.session.commit()

    return redirect("/signup")


##############################################################################
# Messages routes:


@app.route("/messages/new", methods=["GET", "POST"])
def messages_add():
    """Add a message:

    Show form if GET. If valid, update message and redirect to user page.
    """

    if not g.user:
        flash("Access unauthorized.", "danger")
        return redirect("/")

    form = MessageForm()

    if form.validate_on_submit():
        msg = Message(text=form.text.data)
        g.user.messages.append(msg)
        db.session.commit()

        return redirect(f"/users/{g.user.id}")

    return render_template("messages/new.html", form=form)


@app.route("/messages/<int:message_id>", methods=["GET"])
def messages_show(message_id):
    """Show a message."""

    msg = Message.query.get(message_id)
    return render_template("messages/show.html", message=msg)


@app.route("/messages/<int:message_id>/delete", methods=["POST"])
def messages_destroy(message_id):
    """Delete a message."""

    if not g.user:
        flash("Access unauthorized.", "danger")
        return redirect("/")

    msg = Message.query.get(message_id)
    db.session.delete(msg)
    db.session.commit()

    return redirect(f"/users/{g.user.id}")


##############################################################################
# Likes
@app.route("/users/add_like/<int:msg_id>", methods=["POST"])
def add_like(msg_id):
    if not g.user:
        flash("Access unauthorized.", "danger")
        return redirect("/")

    liked_message = Message.query.get_or_404(msg_id)
    if liked_message.user_id == g.user.id:
        return abort(403)

    user_likes = g.user.likes

    if liked_message in user_likes:
        g.user.likes = [like for like in user_likes if like != liked_message]
    else:
        g.user.likes.append(liked_message)
    db.session.commit()
    return redirect("/")

#not used
@app.route("/users/<int:user_id>/likes")
def show_liked_posts(user_id):

    user = User.query.get_or_404(user_id)
    likes = [like.message_id for like in Likes.query.filter_by(user_id=g.user.id).all()]

    return render_template(
        "/messages/liked_messages.html", messages=user.likes, likes=likes, user=user
    )

@app.route("/users/<int:user_id>/organizations")
def show_liked_orgs(user_id):

    user = User.query.get_or_404(user_id)
    org_likes = [saved_org.org_id for saved_org in SavedOrgs.query.filter_by(username=g.user.username).all()]

    return render_template(
        "/organizations/liked_organizations.html", orgs=user.org_likes, org_likes=org_likes, user=user
    )

@app.route("/users/<int:user_id>/animals")
def show_liked_animals(user_id):

    user = User.query.get_or_404(user_id)
    animal_likes = [saved_animal.animal_id for saved_animal in SavedAnimals.query.filter_by(username=g.user.username).all()]

    return render_template(
        "/animals/liked_animals.html", animals=user.animal_likes, animal_likes=animal_likes, user=user
    )


# @app.route("/users/<int:user_id>/likes", ["POST"])
# def show_liked_posts(user_id):

#     user = User.query.get(user_id)

#     likes = [like.message_id for like in Likes.query.filter_by(user_id=user_id).all()]

#     return render_template(
#         "/messages/liked_messages.html", messages=user.likes, likes=likes
#     )


@app.route("/users/add_like_v2/<int:msg_id>", methods=["POST"])
def add_like_v2(msg_id):
    if not g.user:
        flash("Access unauthorized.", "danger")
        return redirect(f"/users/{g.user.id}/likes")

    liked_message = Message.query.get_or_404(msg_id)
    if liked_message.user_id == g.user.id:
        return abort(403)

    user_likes = g.user.likes

    if liked_message in user_likes:
        g.user.likes = [like for like in user_likes if like != liked_message]
    else:
        g.user.likes.append(liked_message)
    db.session.commit()
    return redirect(f"/users/{g.user.id}/likes")


####################### start of project


@app.route("/organizations/<int:page_num>")
def list_organizations(page_num):
    """Page with listing of organizations from API.

    Can take a 'q' param in querystring to search by that username.
    """

    print('THIS IS MY SESSION TOKENNNNN!!!!!!!!!!!!!!!!!!!!')
    print(session["token"])
    
    location = request.args.get("location")
    state = request.args.get("state")
    token = session["token"]
    headers = {"Authorization": f"Bearer {token}"}
    
    states = ["AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DC", "DE", "FL", "GA", 
          "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", 
          "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", 
          "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", 
          "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY"]


    if not location and not state:
        res = requests.get(
            f"https://api.petfinder.com/v2/organizations?page={page_num}&limit=42",
            headers=headers,
        )

        data = res.json()
        organizations = data["organizations"]
        for org in organizations:
            print("didn't search")
            print(org["name"])
    if location:
        res = requests.get(
            f"https://api.petfinder.com/v2/organizations?page={page_num}&limit=42&location={location}",
            headers=headers,
        )

        data = res.json()
        organizations = data["organizations"]
        
    if state:
        res = requests.get(
            f"https://api.petfinder.com/v2/organizations?page={page_num}&limit=42&state={state}",
            headers=headers,
        )

        data = res.json()
        organizations = data["organizations"]
        for org in organizations:

            print(org["name"])
            print("searched")
    
    org_likes = [saved_org.id for saved_org in g.user.org_likes]


    return render_template(
        "organizations/index.html", organizations=organizations, page_num=page_num + 1, org_likes=org_likes, states=states, state=state, location=location
    )


@app.route("/animals/<int:page_num>")
def list_animals(page_num):
    """Page with listing of organizations from API.

    Can take a 'q' param in querystring to search by that username.
    """

    name = request.args.get("name")
    type = request.args.get("type")
    gender = request.args.get('gender')
    token = session["token"]
    headers = {"Authorization": f"Bearer {token}"}
    
    
    type_res = requests.get(
            f"https://api.petfinder.com/v2/types",
            headers=headers,
        )

    data = type_res.json()
    types = data["types"]   
    

    if not type and not name and not gender:
        res = requests.get(
            f"https://api.petfinder.com/v2/animals?page={page_num}&limit=42",
            headers=headers,
        )

        data = res.json()
        animals = data["animals"]

        
        
        # for animal in animals:
        #     print(animal["name"])
    if type:
        res = requests.get(
            f"https://api.petfinder.com/v2/animals?page={page_num}&limit=42&type={type}",
            headers=headers,
        )

        data = res.json()
        if('animals' in data):
            animals = data["animals"]
        else:   
            animals = []
        
    if name:
        res = requests.get(
            f"https://api.petfinder.com/v2/animals?page={page_num}&limit=42&name={name}",
            headers=headers,
        )

        data = res.json()
        animals = data["animals"]
        
    if gender:
        res = requests.get(
            f"https://api.petfinder.com/v2/animals?page={page_num}&limit=42&gender={gender}",
            headers=headers,
        )

        data = res.json()
        animals = data["animals"]
    
    
        
    animal_likes = [int(saved_animal.id) for saved_animal in g.user.animal_likes]

    return render_template("animals/index.html", animals=animals, page_num=page_num + 1, animal_likes=animal_likes, name=name, types=types, type=type, gender=gender)


@app.route("/animals/details/<int:animal_id>")
def animal_details(animal_id):
    """Page with listing of organizations from API.

    Can take a 'q' param in querystring to search by that username.
    """

    search = request.args.get("q")
    token = session["token"]

    if not search:
        headers = {"Authorization": f"Bearer {token}"}
        res = requests.get(
            f"https://api.petfinder.com/v2/animals/{animal_id}", headers=headers,
        )

        data = res.json()
        animal = data["animal"]

    return render_template("animals/details.html", animal=animal)


@app.route("/organizations/details/<org_id>")
def organization_details(org_id):
    """Page with listing of organizations from API.

    Can take a 'q' param in querystring to search by that username.
    """

    search = request.args.get("q")
    token = session["token"]

    if not search:
        headers = {"Authorization": f"Bearer {token}"}
        res = requests.get(
            f"https://api.petfinder.com/v2/organizations/{org_id}", headers=headers,
        )

        data = res.json()
        organization = data["organization"]

    return render_template("organizations/details.html", org=organization)


@app.route("/organizations/search")
def search_for_organizations():
    """Search for organizations."""
    if not g.user:
        flash("Please login first!", "danger")
        return redirect("/login")
    else:
        search_for = request.args.get("search_for").strip()
        if len(search_for) < 2:
            flash("Please enter at least 2 characters to search!", "danger")
            return redirect("/organizations/1")
        else:
            small_images = find_some_art(search_for)
            if session["return"] == "success":
                user = User.query.get(session["username"])
                return render_template(
                    "found_artworks.html",
                    art=small_images,
                    search_for=search_for,
                    user=user,
                )
            else:
                return redirect("/artwork/add")


@app.route("/animal/save/<animal_id>", methods=["POST"])
def add_to_saved_animals(animal_id):
    """add to saved animals."""
    if not g.user:
        flash("Please login first!", "danger")
        return redirect("/login")
    else:
        animal = Animal.query.get(animal_id)

        if animal == None:
            get_animal = get_the_animal(animal_id)
            new_animal = Animal(
                id=animal_id,
                name=get_animal["name"],
                img_url=get_animal["img_url"],
                description=get_animal["description"],
            )
            db.session.add(new_animal)
            db.session.commit()
            new_user_animal = SavedAnimals(username=g.user.username, animal_id=animal_id)
            db.session.add(new_user_animal)
            db.session.commit()
        else:
            liked_animal = Animal.query.get_or_404(animal_id)
            animal_likes = g.user.animal_likes
            
            if liked_animal in animal_likes:
                g.user.animal_likes = [animal for animal in animal_likes if animal != liked_animal]
            else:
                g.user.animal_likes.append(liked_animal)
                # new_user_org = SavedOrgs(username=g.user.username, org_id=org_id)
                # db.session.add(new_user_org)
            db.session.commit()
        
        return redirect(request.referrer)
    
@app.route("/organization/save/<org_id>", methods=["POST"])
def add_to_saved_orgs(org_id):
    """add to collection."""
    if not g.user:
        flash("Please login first!", "danger")
        return redirect("/login")
    else:
        org = Organization.query.get(org_id)

        if org == None:
            get_org = get_the_org(org_id)
            new_org = Organization(
                id=org_id,
                name=get_org["name"],
                img_url=get_org["img_url"],
                mission_statement=get_org["mission_statement"],
            )
            db.session.add(new_org)
            db.session.commit()
            new_user_org = SavedOrgs(username=g.user.username, org_id=org_id)
            db.session.add(new_user_org)
            db.session.commit()
        else:
            liked_org = Organization.query.get_or_404(org_id)
            org_likes = g.user.org_likes
            
            if liked_org in org_likes:
                g.user.org_likes = [org for org in org_likes if org != liked_org]
            else:
                g.user.org_likes.append(liked_org)
                # new_user_org = SavedOrgs(username=g.user.username, org_id=org_id)
                # db.session.add(new_user_org)
            db.session.commit()
        return redirect(request.referrer)


@app.route("/artwork/addtocollection/<int:org_id>")
def add_to_collection(org_id):
    """add to collection."""
    if "username" not in session:
        flash("Please login first!", "danger")
        return redirect("/login")
    else:
        org = Organization.query.get(org_id)
        if org == None:
            title = session["title"]
            artist = session["artist"]
            department = session["department"]
            creditline = session["creditLine"]
            image = session["image_link"]
            image_full = session["image_link_full"]
            if image == "":
                image = "https://images.metmuseum.org/CRDImages/eg/web-large/Images-Restricted.jpg"
            if image_full == "":
                image_full = "https://images.metmuseum.org/CRDImages/eg/web-large/Images-Restricted.jpg"
            new_art = Artwork(
                id=artwork_id,
                title=title,
                artist=artist,
                department=department,
                creditline=creditline,
                image_link=image,
                image_link_full=image_full,
            )
            db.session.add(new_art)
            db.session.commit()
            new_user_art = UserArtwork(
                username=session["username"], artwork_id=artwork_id
            )
            db.session.add(new_user_art)
            db.session.commit()
        else:
            user_art = UserArtwork.query.filter_by(
                username=session["username"], artwork_id=artwork_id
            ).first()
            if user_art == None:
                new_user_art = UserArtwork(
                    username=session["username"], artwork_id=artwork_id
                )
                db.session.add(new_user_art)
                db.session.commit()
        return redirect(f"/user/{session['username']}")


def get_the_org(org_id):
    """get the details for a work of art when we are not sure if the art id is valid"""
    org = Organization.query.get(
        org_id
    )  # see if we have it in the db and if not call the api

    if org == None:
        try:

            token = session["token"]
            headers = {"Authorization": f"Bearer {token}"}
            get_org = requests.get(
                f"https://api.petfinder.com/v2/organizations/{org_id}", headers=headers
            )
            data = get_org.json()
            j_org = data["organization"]
            print(j_org)
          
            org = {
                "id": org_id,
                "name": j_org["name"],
                "mission_statement": j_org["mission_statement"],
            }
            
            if len(j_org['photos']) == 0:
                org['img_url'] = 'https://img.freepik.com/free-vector/cute-dog-sitting-cartoon-vector-icon-illustration-animal-nature-icon-concept-isolated-premium-vector-flat-cartoon-style_138676-3671.jpg'
            else:
                org['img_url'] = j_org["photos"][0]["medium"]
            print(org)
           
                
            print("++++++++++++++++++++++++++++++++++++")
            print(org)
            print("+++++++++++++++++++++++++++++++++")
            return org
        except Exception as e:
            flash("An unexpected error occurred.", "danger")
            session["return"] = "failed"
            return
    session["return"] = "success"
    return org

def get_the_animal(animal_id):
    """get the details for an animal when we are not sure if the animal is within our database"""
    animal = Organization.query.get(
        animal_id
    )  # see if we have it in the db and if not call the api

    if animal == None:
        try:

            token = session["token"]
            headers = {"Authorization": f"Bearer {token}"}
            get_animal = requests.get(
                f"https://api.petfinder.com/v2/animals/{animal_id}", headers=headers
            )
            data = get_animal.json()
            j_animal = data["animal"]
            # print(j_animal)
          
            animal = {
                "id": animal_id,
                "name": j_animal["name"],
                "description": j_animal["description"],
            }
            
            if len(j_animal['photos']) == 0:
                animal['img_url'] = 'https://img.freepik.com/free-vector/cute-dog-sitting-cartoon-vector-icon-illustration-animal-nature-icon-concept-isolated-premium-vector-flat-cartoon-style_138676-3671.jpg'
            else:
                animal['img_url'] = j_animal["photos"][0]["medium"]
            # print(animal)
            
           
            # print("++++++++++++++++++++++++++++++++++++")
            # print(animal)
            # print("+++++++++++++++++++++++++++++++++")
            return animal
        except Exception as e:
            flash("An unexpected error occurred.", "danger")
            session["return"] = "failed"
            return
    session["return"] = "success"
    return animal

##############################################################################
# Homepage and error pages


@app.route("/")
def homepage():
    """Show homepage:

    - anon users: no messages
    - logged in: 100 most recent messages of followed_users
    """

    if g.user:

        return render_template("home.html")

    else:
        return render_template("home-anon.html")


########################################################
def find_some_org(search_for):
    """Call the api with the search term"""
    res = requests.get(
        f"https://collectionapi.metmuseum.org/public/collection/v1/search?hasImages=true&q={search_for}"
    )
    data = res.json()
    if data["total"] == 0:
        flash(
            "No artworks were found for that search! Please try again with a different search term.",
            "danger",
        )
        session["return"] = "failed"
        return
    else:
        small_images = find_the_images(data)
    session["return"] = "success"
    return small_images


def get_the_art(artwork_id):
    """get the details for a work of art when we are not sure if the art id is valid"""
    art = Artwork.query.get(
        artwork_id
    )  # see if we have it in the db and if not call the api
    if art == None:
        try:
            get_art = requests.get(
                f"https://collectionapi.metmuseum.org/public/collection/v1/objects/{artwork_id}"
            )
            j_org = get_art.json()
            if j_org["primaryImageSmall"] == "":
                j_org[
                    "primaryImageSmall"
                ] = "https://images.metmuseum.org/CRDImages/eg/web-large/Images-Restricted.jpg"
            if j_org["primaryImage"] == "":
                j_org[
                    "primaryImage"
                ] = "https://images.metmuseum.org/CRDImages/eg/web-large/Images-Restricted.jpg"
            session["title"] = j_org["title"]
            session["artist"] = j_org["artistDisplayName"]
            session["department"] = j_org["department"]
            session["creditLine"] = j_org["creditLine"]
            session["image_link"] = j_org["primaryImageSmall"]
            session["image_link_full"] = j_org["primaryImage"]
            art = Artwork(
                id=artwork_id,
                title=j_org["title"],
                artist=j_org["artistDisplayName"],
                department=j_org["department"],
                creditline=j_org["creditLine"],
                image_link=j_org["primaryImageSmall"],
                image_link_full=j_org["primaryImage"],
            )
        except Exception as e:
            flash("An unexpected error occurred.", "danger")
            session["return"] = "failed"
            return
    session["return"] = "success"
    return art


##############################################################################
# Turn off all caching in Flask
#   (useful for dev; in production, this kind of stuff is typically
#   handled elsewhere)
#
# https://stackoverflow.com/questions/34066804/disabling-caching-in-flask


@app.after_request
def add_header(req):
    """Add non-caching headers on every request."""

    req.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    req.headers["Pragma"] = "no-cache"
    req.headers["Expires"] = "0"
    req.headers["Cache-Control"] = "public, max-age=0"
    return req

