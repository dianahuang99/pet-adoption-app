from locale import currency
import os

from flask import Flask, render_template, request, flash, redirect, session, g, abort
from flask_debugtoolbar import DebugToolbarExtension
from numpy import nanmax
from sqlalchemy.exc import IntegrityError
from sympy import preview
from time import sleep
from threading import Timer
from datetime import datetime, timedelta


from forms import UserAddForm, LoginForm, EditUserForm
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
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=30)

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

def getToken():
    res = requests.post(
                "https://api.petfinder.com/v2/oauth2/token", json=token_request
            )
    session["token"] = res.json()["access_token"]
    session["timer"] = 3600
    
def setTimerToZero():
    session['timer'] = 0
    
    # Example implementation of retrieve_token_expiration_time function
def retrieve_token_expiration_time():
    expiration_time = session.get('token_expiration_time')
    return expiration_time
    
def token_expired():
    expiration_time = retrieve_token_expiration_time()
    current_time = datetime.now()
    return current_time > expiration_time



@app.route("/login", methods=["GET", "POST"])
def login():
    """Handle user login."""

    form = LoginForm()

    if form.validate_on_submit():
        user = User.authenticate(form.username.data, form.password.data)

        if user:
            do_login(user)
            flash(f"Hello, {user.username}!", "success")
            getToken()
            t = Timer(3600.0, setTimerToZero)
            t.start()
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



@app.route("/users/<int:user_id>")
def users_show(user_id):
    """Show user profile."""

    user = User.query.get_or_404(user_id)

    
    return render_template("users/show.html", user=user)


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

@app.route("/users/<int:user_id>/organizations")
def show_liked_orgs(user_id):

    user = User.query.get_or_404(user_id)
    org_likes = [saved_org.org_id for saved_org in SavedOrgs.query.filter_by(user_id=g.user.id).all()]

    return render_template(
        "/organizations/liked_organizations.html", orgs=user.org_likes, org_likes=org_likes, user=user
    )

@app.route("/users/<int:user_id>/animals")
def show_liked_animals(user_id):

    user = User.query.get_or_404(user_id)
    animal_likes = [saved_animal.animal_id for saved_animal in SavedAnimals.query.filter_by(user_id=g.user.id).all()]

    return render_template(
        "/animals/liked_animals.html", animals=user.animal_likes, animal_likes=animal_likes, user=user
    )

@app.route("/organizations/<int:page_num>")
def list_organizations(page_num):
    """Page with listing of organizations from API.

    Can take a 'q' param in querystring to search by that username.
    """
    
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
            new_user_animal = SavedAnimals(user_id=g.user.id, animal_id=animal_id)
            db.session.add(new_user_animal)
            db.session.commit()
        else:
            liked_animal = Animal.query.get_or_404(animal_id)
            animal_likes = g.user.animal_likes
            
            if liked_animal in animal_likes:
                g.user.animal_likes = [animal for animal in animal_likes if animal != liked_animal]
            else:
                g.user.animal_likes.append(liked_animal)
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
            new_user_org = SavedOrgs(user_id=g.user.id, org_id=org_id)
            db.session.add(new_user_org)
            db.session.commit()
        else:
            liked_org = Organization.query.get_or_404(org_id)
            org_likes = g.user.org_likes
            
            if liked_org in org_likes:
                g.user.org_likes = [org for org in org_likes if org != liked_org]
            else:
                g.user.org_likes.append(liked_org)
            db.session.commit()
        return redirect(request.referrer)



def get_the_org(org_id):
    """get the details for an organizationn"""
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
            animal = {
                "id": animal_id,
                "name": j_animal["name"],
                "description": j_animal["description"],
            }
            
            if len(j_animal['photos']) == 0:
                animal['img_url'] = 'https://img.freepik.com/free-vector/cute-dog-sitting-cartoon-vector-icon-illustration-animal-nature-icon-concept-isolated-premium-vector-flat-cartoon-style_138676-3671.jpg'
            else:
                animal['img_url'] = j_animal["photos"][0]["medium"]
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

