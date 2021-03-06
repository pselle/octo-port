"""
Top-level doc comment.
"""
from flask import Flask, request, session, g, redirect, url_for, \
     abort, render_template, flash, send_file
from werkzeug.urls import url_decode, url_encode

import os
import re
import StringIO
import requests
import json
import csv
import urlparse
import pdb

# CONSTANTS
DEBUG = True
GITHUB_CLIENT_ID = os.environ["GITHUB_CLIENT_ID"]
GITHUB_CLIENT_SECRET = os.environ["GITHUB_CLIENT_SECRET"]
REQUESTED_SCOPES = ["user", "repo"]
# Field names used in CSV output rows
FIELDNAMES = [
    "created_at",    # created_at [formatted?]
    "updated_at",    # updated_at
    "closed_at",     # closed_at [formatted?]
    "created_by",    # user
    "assignee",      # assignee.login
    "number",        # number
    "html_url",      # html_url
    "pull_request",  # pull_request.html_url
    "state",         # state
    "labels",        # ", ".join([name for label in labels])
    "milestone",     # milestone.title
    "comments",      # comments [it's just a count, which is fine]
    "title",         # title
    "body",          # body
]

SECRET_KEY = "something super secret"

# Github API root URL
API_ROOT = "https://api.github.com"

# Number of results to show per API request; 100 is max
RESULTS_PER_PAGE = 100

# APP CONFIG
app = Flask(__name__)
app.config.from_object(__name__)


# ROUTES
@app.route("/")
def root():
    if not session.has_key("token") and not request.args.get("code"):
        params = {
            "client_id": GITHUB_CLIENT_ID,
            "scope": ",".join(REQUESTED_SCOPES)
        }
        auth_url = "https://github.com/login/oauth/authorize?{params}"
        return redirect(auth_url.format(params=url_encode(params)))
    
    if request.args.get("code"):
        # post the code back to Github to request an access token
        params = {
            "client_id": GITHUB_CLIENT_ID,
            "client_secret": GITHUB_CLIENT_SECRET,
            "code": request.args.get("code")
        }
        auth_url = "https://github.com/login/oauth/access_token"
        response = requests.post(auth_url, params=params)
        response_body = urlparse.parse_qs(response.content)
        session["token"] = response_body["access_token"][0]

    return render_template("home.jinja2")

@app.route("/gimme-csv", methods=['POST', 'GET'])
def build():
    github_string = request.form["github-string"]
    parse_result = urlparse.urlparse(github_string)

    q = urlparse.parse_qs(parse_result.query)
    path = parse_result.path.split('/')[1:]
    username = path[0]
    repository = path[1]
    params = {}

    # path will always be issues/created, issues/mentioned, etc; no combinations
    if 'created_by' in path:
        params['created'] = path[-1]
    if 'mentioned' in path:
        params['mentioned'] = path[-1]
    if 'subscribed' in path:
        params['subscribed'] = path[-1]
    if 'assigned' in path:
        params['assigned'] = path[-1]
    if 'state' in q:
        params['state'] = ','.join(q['state'])
    if 'labels' in q:
        params['labels'] = ','.join(q['labels'])
    if 'milestone' in q:
        params['milestones'] = ','.join(q['milestone'])
    if 'sort' in q:
        params['sort'] = ','.join(q['sort'])
    if 'direction' in q:
        params['direction'] = ','.join(q['direction'])
    if 'since' in q:
        params['since'] = ','.join(q['since'])

    issue_path = "/repos/{username}/{repository}/issues"
    response = api_request(issue_path.format(username=username, repository=repository),
                           params)
    issues = json.loads(response.content)

    def next_page_url(response):
        "Get the URL of the next result page from the API response."

        next_pattern = r'<([^>]+)>; rel="next"'
        link_header = response.headers["link"]

        if not link_header:
            return False

        match = re.search(next_pattern, link_header)
        return match and match.group(1)

    while next_page_url(response) is not None:
        response = api_request(next_page_url(response))
        issues.extend(json.loads(response.content))

    return send_file(build_csv(issues),
                     attachment_filename="issues.csv",
                     as_attachment=True)

# UTILITY
def build_csv(issues):
    """
    Converts the supplied issues to CSV, saving them under the supplied
    filename. Accepts a list of issue dicts as given by the Github API.
    Returns the file handle of the output StringIO.
    """

    output_file = StringIO.StringIO()
    csv_writer = csv.DictWriter(output_file, FIELDNAMES)

    # build header row: the dict(zip(x, x)) yields {"heading": "heading", ...}
    csv_writer.writerow(dict(zip(FIELDNAMES, [name.encode("utf-8") for name in FIELDNAMES])))

    for issue in issues:
        csv_writer.writerow(issue_to_row(issue))

    output_file.seek(0)
    return output_file

def issue_to_row(issue):
    """
    Converts an issue dictionary from JSON into a one-dimensional dictionary
    suitable for CSV writing.
    """

    row = {}
    row["created_at"] = issue["created_at"]
    row["updated_at"] = issue["updated_at"]
    row["closed_at"] = issue["closed_at"]
    row["created_by"] = issue["user"]["login"]
    if issue["assignee"]:
        row["assignee"] = issue["assignee"]["login"]
    row["number"] = issue["number"]
    row["html_url"] = issue["html_url"]
    if issue["pull_request"]:
        row["pull_request"] = issue["pull_request"]["html_url"]
    row["state"] = issue["state"]
    row["labels"] = ", ".join([label["name"] for label in issue["labels"]])
    if issue["milestone"]:
        row["milestone"] = issue["milestone"]["title"]
    row["comments"] = issue["comments"]
    row["title"] = issue["title"]
    row["body"] = issue["body"]

    # encode as UTF-8, since CSV must be ASCII; clients will decode
    for key, value in row.items():
        if hasattr(value, "encode"): # only encode encodables!
            row[key] = value.encode("utf-8")

    return row


def api_request(path, params=None):
    params = params or {}
    params["access_token"] = session["token"]

    if not params.has_key("per_page"):
        params["per_page"] = RESULTS_PER_PAGE

    # TODO: show error page if response is 404
    return requests.get(urlparse.urljoin(API_ROOT, path),
                        params=params)

# USE AWFUL BUT STANDARD-ISSUE PYTHON HACK TO RUN THE SCRIPT
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
