from EasyDraft import app, database, login_manager, yahoo
from flask import g, render_template, redirect, request, url_for, flash, session
from flask.ext.login import LoginManager, current_user, login_required, login_user, logout_user
from forms import LoginForm, RegistrationForm, ChangePassForm, NewLeagueForm, LeagueRequirementsForm, \
                    DraftSetupForm, DraftSearchForm
from process_forms import process_league_form
from EasyDraft.oauth.yahoo_oauth import yahoo_get_resource
import hashlib


@login_manager.user_loader
def load_user(user_id):
    return database.get_user(user_id)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/about')
def about():
    return render_template('about.html')

@app.route("/accounts/login", methods=["GET", "POST"])
def login():
    form = LoginForm()
    error = False
    if request.method == 'POST' and form.validate():
        m = hashlib.md5()
        m.update(form.password.data)
        user = database.get_user(username=form.username.data, password=m.hexdigest())
        if user is not None:
            login_user(user)
            return redirect(request.args.get("next") or url_for("index"))
        else:
            error=True
    return render_template("accounts/login.html", form=form, error=error)

@app.route("/accounts/logout")
@login_required
def logout():
    logout_user()
    return redirect(request.args.get("next") or url_for("index"))

@app.route("/accounts/register", methods=["GET", "POST"])
def register():
    form = RegistrationForm()
    username_error = False
    if request.method == 'POST' and form.validate():
        try:
            m = hashlib.md5()
            m.update(form.password.data)
            user = database.insert_user(form.username.data, form.email.data, m.hexdigest())
            if user is not None:
                login_user(user)
            #flash("Successfully Registered!")
            return redirect(request.args.get("next") or url_for("index"))
        except Exception:
            username_error = True
    return render_template("accounts/register.html", form=form, username_error=username_error)

@app.route("/accounts/password/change", methods=["GET", "POST"])
@login_required
def change_pass():
    form = ChangePassForm()
    error = False
    if request.method == 'POST' and form.validate():
        m = hashlib.md5()
        m.update(form.old_password.data)
        user = database.get_user(username=current_user.username, password=m.hexdigest())
        if user is not None:
            m = hashlib.md5()
            m.update(form.password.data)
            user = database.update_user(username=current_user.username, password=m.hexdigest())
            return redirect(url_for("change_pass_success"))
        error = True
    return render_template("accounts/password_change_form.html", form=form, error=error)

@app.route("/accounts/password/change/success")
def change_pass_success():
    return render_template("accounts/password_change_done.html")

@app.route("/accounts/email/change", methods=["GET", "POST"])
@login_required
def change_email():
    success = False
    if request.method == 'POST' and request.form['email']:
        user = database.update_user(username=current_user.username, email=request.form['email'])
        success = True
        user = database.get_user(username=current_user.username)
        if user is not None:
            login_user(user)
    return render_template("accounts/change_email.html", success=success)

@app.route("/accounts/delete", methods=["GET", "POST"])
@login_required
def delete_account():
    success = True
    user = database.update_user(username=current_user.username, is_active=False)
    logout_user()
    return render_template("accounts/delete.html", success=success)

@yahoo.tokengetter
def get_yahoo_token(token=None):
    return session.get('yahoo_token')

@app.route("/oauth/yahoo")
@login_required
def yahoo_oauth():
    if 'yahoo_token' in session.keys():
        del session['yahoo_token']
    try:
        return yahoo.authorize(callback=url_for('oauth_authorized', next=request.args.get('next') or request.referrer or None))
    except:
        return redirect(url_for('index'))

@app.route('/oauth/authorized')
@yahoo.authorized_handler
def oauth_authorized(resp):
    next_url = request.args.get('next') or url_for('index')
    print resp
    if resp is None:
        flash(u'You denied the request to sign into Yahoo.')
        return redirect(next_url)

    session['yahoo_token'] = (
            resp['oauth_token'],
            resp['oauth_token_secret']
    )
    return redirect(next_url)

@app.route("/players/update/all")
def update_all_players(i=0, stat_map=None):
    if not 'yahoo_token' in session.keys():
        return redirect(url_for('yahoo_oauth', next=url_for('update_all_players') or None))
    nfl_game_key = 'nfl'
    my_league_id = '840811'
    my_league_key = nfl_game_key + '.l.' + my_league_id
    if stat_map is None:
        resp, content = yahoo_get_resource('game/' + nfl_game_key + '/stat_categories', 
                session['yahoo_token'][0], session['yahoo_token'][1])
        if resp.status == 401:
            return redirect(url_for('yahoo_oauth', next=url_for('update_all_players') or None))
        stats = content['fantasy_content']['game'][1]['stat_categories']['stats']
        stat_map = dict()
        for stat in stats:
            stat_map[str(stat['stat']['stat_id'])] = stat['stat']['display_name']
    params = { 'sort': 'NAME', 'start': str(i) }
    resp, content = yahoo_get_resource('league/' + my_league_key + '/players/stats', 
            session['yahoo_token'][0], session['yahoo_token'][1], extras=params)
    if resp.status == 401:
        return redirect(url_for('yahoo_oauth', next=url_for('update_all_players') or None))
    if resp.status != 200:
        flash('An Error Occured While Loading Players')
    players = content['fantasy_content']['league'][1]['players']
    for key in players.keys():
        if key != u'count':
            pos = []
            stats = []
            for item in players[key]['player'][0]:
                if not isinstance(item, dict):
                    continue
                if 'player_id' in item.keys():
                    player_id = item['player_id']
                if 'name' in item.keys():
                    first_name = item['name']['first']
                    last_name = item['name']['last']
                if 'editorial_team_abbr' in item.keys():
                    nfl_team = item['editorial_team_abbr']
                if 'eligible_positions' in item.keys():
                    for position in item['eligible_positions']:
                        pos.append(position['position'])
            for stat in players[key]['player'][1]['player_stats']['stats']:
                stats.append(stat['stat'])
            database.insert_player(player_id, first_name, last_name, nfl_team)
            print "Inserted", player_id, first_name, last_name, nfl_team
            for p in pos:
                database.insert_position(player_id, p)
            for stat in stats:
                database.insert_stat(stat['stat_id'], player_id, stat['value'], stat_map[stat['stat_id']])

    if players[u'count'] < 25:
        print "Done getting players"
        return redirect(request.args.get('next') or url_for('index'))
    else:
        return update_all_players(i+25, stat_map)
    
@app.route("/user/leagues")
@login_required
def my_leagues():
    leagues = database.my_leagues(current_user.get_id())
    return render_template('my_leagues.html', leagues=leagues)

@app.route("/teams/get_team")
@login_required
def get_team():
    league_id = request.args.get('league_id')
    team_id = request.args.get('team_id')
    valid = database.user_in_league(current_user.get_id(), league_id)
    print valid
    if not valid:
        return redirect(url_for('index'))
    team = database.get_team(team_id)
    players = database.get_team_players(team_id)
    return render_template('my_team.html', players=players, team=team)

@app.route("/league/get_league")
@login_required
def get_league():
    league_id = request.args.get('league_id')
    valid = database.user_in_league(current_user.get_id(), league_id)
    if not valid:
        return redirect(url_for('index'))
    league = database.get_league(league_id)
    teams = database.get_league_teams(league_id)
    return render_template('league.html', league=league, teams=teams)

@app.route("/league/draft/success")
@login_required
def draft_success():
    league_id = request.args.get('league_id')
    valid = database.user_in_league(current_user.get_id(), league_id)
    if not valid:
        return redirect(url_for('index'))
    league = database.get_league(league_id)
    return render_template('draft_success.html', league=league)

@app.route("/user/new_league", methods=["GET", "POST"])
def new_league():
    form = NewLeagueForm()
    if request.method == 'POST' and form.validate():
        if form.pull_from_yahoo.data:
            pass
        else:
            return redirect(url_for('new_league_setup', league_name=form.league_name.data, yahoo_league_id=form.yahoo_league_id.data))
    return render_template("new_league.html", form=form)

def get_yahoo_league(league_id):
   pass 

@app.route("/user/new_league/setup", methods=["GET", "POST"])
def new_league_setup():
    league_name = request.args.get('league_name')
    yahoo_league_id = request.args.get('yahoo_league_id')
    form = LeagueRequirementsForm()
    if request.method == 'POST' and form.validate():
        league_id = process_league_form(league_name, yahoo_league_id, form)
        return redirect(url_for('new_league_success', league_name=league_name, league_id=league_id))
    return render_template("new_league_setup.html", league_name=league_name, form=form)

@app.route("/user/new_league/success")
def new_league_success():
    return render_template("new_league_success.html", league_name=request.args.get('league_name'), \
                            league_id=request.args.get('league_id'))

@app.route("/league/draft/setup", methods=["GET", "POST"])
@login_required
def draft_setup():
    league_id = request.args.get('league_id')
    valid = database.user_in_league(current_user.get_id(), league_id)
    if not valid:
        return redirect(url_for('index'))
    form = DraftSetupForm()
    league = database.get_league(league_id)
    if request.method =='POST' and form.validate():
        return redirect(url_for('draft_day', time=form.draft_time.data, league_id=league_id, \
                order=form.draft_order.data, selection=form.draft_positions.data))
    return render_template("draft_setup.html", form=form, league=league)

@app.route("/league/draft_day", methods=["GET", "POST"])
@login_required
def draft_day():
    draft = dict()
    draft['league_id'] = request.args.get('league_id')
    draft['time'] = request.args.get('time')
    draft['order'] = request.args.get('order')
    draft['selection'] = request.args.get('selection')
    valid = database.user_in_league(current_user.get_id(), draft['league_id'])
    if not valid or not draft['league_id'] or not draft['time']:
        return redirect(url_for('index'))
    teams = database.get_league_teams(draft['league_id'])
    draft['current_team'] = int(request.args.get('current_team') or 0)
    draft['direction'] = int(request.args.get('direction') or 1)
    print teams, draft['current_team'], draft['direction']
    if request.args.get('pick') != '0' and request.args.get('pick') is not None:
        print "Made Pick"
        pick_id = request.args.get('pick')
        database.insert_pick(teams[draft['current_team']][0], pick_id)
        num_picks = database.get_total_draft(draft['league_id'])[0]
        total_picks = int(database.get_league(draft['league_id'])[2]) * len(teams)
        print num_picks, total_picks
        if num_picks >= total_picks:
            database.complete_draft(draft['league_id'])
            return redirect(url_for('draft_success', league_id=draft['league_id']))
        if draft['current_team'] == len(teams)-1 and draft['direction'] == 1:
            draft['direction'] = draft['direction'] * -1
        elif draft['current_team'] == 0 and draft['direction'] == -1:
            draft['direction'] = draft['direction'] * -1
        else:
            draft['current_team'] = draft['current_team'] + draft['direction']
    position = request.args.get('position')
    nfl_team = request.args.get('nfl_team')
    player_name = request.args.get('player')
    order_by = request.args.get('sort')
    limit = request.args.get('max_return')
    if not order_by:
        order_by = 'last_name'
    if not limit:
        limit = '200'
    players = database.get_players_draft(draft['league_id'], order_by=order_by, position=position, nfl_team=nfl_team, last_name=player_name, limit=limit)
    team_players = database.get_team_players(teams[draft['current_team']][0])
    search = DraftSearchForm()
    return render_template("draft_day.html", draft=draft, players=players, search=search, team=teams[draft['current_team']], team_players=team_players)

