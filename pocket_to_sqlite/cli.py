from concurrent.futures import ThreadPoolExecutor
from itertools import repeat
import time
import click
import json
import urllib.parse
import pathlib
import requests
import sqlite_utils
from . import utils

CONSUMER_KEY = "104708-da187ce0e7f8646d64a06a8"


@click.group()
@click.version_option()
def cli():
    "Save Pocket data to a SQLite database"


@cli.command()
@click.option(
    "-a",
    "--auth",
    type=click.Path(file_okay=True, dir_okay=False, allow_dash=False),
    default="auth.json",
    help="Path to save tokens to, defaults to auth.json",
)
def auth(auth):
    "Save authentication credentials to a JSON file"
    response = requests.post(
        "https://getpocket.com/v3/oauth/request",
        {
            "consumer_key": CONSUMER_KEY,
            "redirect_uri": "https://getpocket.com/connected_applications",
        },
    )
    request_token = dict(urllib.parse.parse_qsl(response.text))["code"]
    click.echo("Visit this page and sign in with your Pocket account:\n")
    click.echo(
        "https://getpocket.com/auth/authorize?request_token={}&redirect_uri={}\n".format(
            request_token, "https://getpocket.com/connected_applications"
        )
    )
    input("Once you have signed in there, hit <enter> to continue")
    # Now exchange the request_token for an access_token
    response2 = requests.post(
        "https://getpocket.com/v3/oauth/authorize",
        {"consumer_key": CONSUMER_KEY, "code": request_token},
    )
    codes = dict(urllib.parse.parse_qsl(response2.text))

    codes["consumer_key"] = CONSUMER_KEY

    auth_data = {}
    auth_path = pathlib.Path(auth)
    if auth_path.exists():
        auth_data = json.loads(auth_path.read_text())

    auth_data.update(
        {
            "pocket_consumer_key": CONSUMER_KEY,
            "pocket_username": codes["username"],
            "pocket_access_token": codes["access_token"],
        }
    )

    open(auth, "w").write(json.dumps(auth_data, indent=4) + "\n")
    click.echo("Authentication tokens written to {}".format(auth))

@cli.command()
@click.argument(
    "db_path",
    type=click.Path(file_okay=True, dir_okay=False, allow_dash=False),
    required=True,
)
@click.option(
    "-a",
    "--auth",
    type=click.Path(file_okay=True, dir_okay=False, allow_dash=False),
    default="auth.json",
    help="Path to auth tokens, defaults to auth.json",
)
@click.option("--errors", is_flag=True, help="Process items which have errors from previous categorization")
@click.option("--save-html", 
    type=click.Path(file_okay=False, dir_okay=True, allow_dash=False), help="Save html into the specified folder")
@click.option("--sync", is_flag=True, help="Send already processed item tags back to Pocket")
@click.option("--sync-num", default=-1, type=click.INT, help="How many to sync (-1 for all)")
@click.option("-s", "--silent", is_flag=True, help="Don't show progress bar")
@click.option(
    "--categorize-url",
    help="URL to use for classification (optional)",
)
def autotag(db_path, auth, sync, sync_num, errors, save_html, silent, categorize_url):
    auth = json.load(open(auth))
    db = sqlite_utils.Database(db_path)
    
    print("Categorizing items...")
    uncategorized = []

    if db["auto_tags"].exists():
        if errors:
            uncategorized = db.query("select * FROM items WHERE status=0 AND item_id IN (SELECT item_id FROM auto_tags where error is NOT NULL)")
        else:
            uncategorized = db.query("SELECT * FROM items WHERE status=0 AND item_id NOT IN (SELECT item_id FROM auto_tags)")
    else:
        db.execute("""
            CREATE TABLE [auto_tags] (
            [item_id] INTEGER PRIMARY KEY REFERENCES [items]([item_id]),
            [error] TEXT,
            [html] TEXT,
            [html_md5] TEXT,
            [likely_categories] TEXT,
            [top_category] TEXT,
            [scores] TEXT,
            [embeddings] TEXT,
            [process_time] FLOAT,
            [created_at] TEXT,
            [synced] INTEGER
        )""")

        uncategorized = db.query("SELECT * FROM items WHERE status=0")

    # Operate in parallel if categorization is happening remotely
    if categorize_url:
        uncategorized = list(uncategorized)
        num_results = 0
        total_items = len(uncategorized)
        print("Entering parallel processing for {} items".format(total_items))
        t1 = time.time()
        for categorize_result in ThreadPoolExecutor(max_workers=6).map(utils.categorize_item, uncategorized, repeat(categorize_url), repeat(save_html)):
            num_results += 1
            print("Received result #{}/{} - {:.2f} seconds since start (item_id {})".format(num_results, total_items, time.time() - t1, categorize_result["categorization"]["item_id"]))
            if categorize_result["error"] == True:
                print("Error categorizing item {}: {}".format(categorize_result["categorization"]["item_id"], categorize_result["categorization"]["error"][:100] ))
            db["auto_tags"].upsert(
                categorize_result["categorization"],
                pk="item_id",
                foreign_keys=("items", "item_id"))
    
        print("Predicted {} results in {:.2f} seconds".format(total_items, time.time() - t1))
    else:
        for item in uncategorized:
            categorize_result = utils.categorize_item(item, categorize_url, save_html)

            if categorize_result["error"] == True:
                print("Error categorizing item: {}".format(categorize_result["categorization"]))

            db["auto_tags"].upsert(
                categorize_result["categorization"],
                pk="item_id",
                foreign_keys=("items", "item_id"))

@cli.command()
@click.argument(
    "db_path",
    type=click.Path(file_okay=True, dir_okay=False, allow_dash=False),
    required=True,
)
@click.option(
    "-a",
    "--auth",
    type=click.Path(file_okay=True, dir_okay=False, allow_dash=False),
    default="auth.json",
    help="Path to auth tokens, defaults to auth.json",
)
@click.option("-n", "--num", default=-1, type=click.INT, help="How many to sync (-1 for all)")
@click.option("-s", "--silent", is_flag=True, help="Don't show progress bar")
def autotag_sync(db_path, auth, num, silent):
    auth = json.load(open(auth))
    db = sqlite_utils.Database(db_path)
    categorized_and_not_synced = []

    if db["auto_tags"].exists():
        categorized_and_not_synced = db.query("select * from auto_tags where synced <> 1 and error is null")

    categorized_and_not_synced = list(categorized_and_not_synced)
    print("{} items remaining to sync".format(len(categorized_and_not_synced)))
    num_to_process = num
    for unsynced in categorized_and_not_synced:
        utils.write_labels_to_pocket(unsynced, auth, db)
        num_to_process -= 1
        if num_to_process == 0:
            break

@cli.command()
@click.argument(
    "db_path",
    type=click.Path(file_okay=True, dir_okay=False, allow_dash=False),
    required=True,
)
@click.option(
    "-a",
    "--auth",
    type=click.Path(file_okay=True, dir_okay=False, allow_dash=False),
    default="auth.json",
    help="Path to auth tokens, defaults to auth.json",
)
@click.option("--all", is_flag=True, help="Fetch all items (not just new ones)")
@click.option("-s", "--silent", is_flag=True, help="Don't show progress bar")
def fetch(db_path, auth, all, silent):
    "Save Pocket data to a SQLite database"
    auth = json.load(open(auth))
    db = sqlite_utils.Database(db_path)
    last_since = None
    if not all and db["since"].exists():
        last_since = db["since"].get(1)["since"]
    fetch = utils.FetchItems(
        auth,
        since=last_since,
        record_since=lambda since: db["since"].insert(
            {"id": 1, "since": since}, replace=True, pk="id"
        ),
    )
    if (all or last_since is None) and not silent:
        total_items = utils.fetch_stats(auth)["count_list"]
        with click.progressbar(fetch, length=total_items) as bar:
            utils.save_items(bar, db)
    else:
        # No progress bar
        print("Fetching items since {}".format(last_since))
        utils.save_items(fetch, db)
    utils.ensure_fts(db)
