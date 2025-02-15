import datetime
import requests
import json
import time
from homepage2vec.model import WebsiteClassifier, Webpage
from sqlite_utils.db import AlterError, ForeignKey
import hashlib
import os

model = WebsiteClassifier()

def save_items(items, db):
    for item in items:
        transform(item)
        authors = item.pop("authors", None)
        items_authors_to_save = []
        if authors:
            authors_to_save = []
            for details in authors.values():
                authors_to_save.append(
                    {
                        "author_id": int(details["author_id"]),
                        "name": details["name"],
                        "url": details["url"],
                    }
                )
                items_authors_to_save.append(
                    {
                        "author_id": int(details["author_id"]),
                        "item_id": int(details["item_id"]),
                    }
                )
            db["authors"].insert_all(authors_to_save, pk="author_id", replace=True)
        db["items"].insert(item, pk="item_id", alter=True, replace=True)
        if items_authors_to_save:
            db["items_authors"].insert_all(
                items_authors_to_save,
                pk=("author_id", "item_id"),
                foreign_keys=("author_id", "item_id"),
                replace=True,
            )

def write_labels_to_pocket(autoclassification,auth, db):
    item_id = autoclassification["item_id"]
    top_category = "autotag-{}".format(autoclassification["top_category"]).lower()

    print("Writing tag {} to item {}".format(top_category, item_id))
    args = {
        "consumer_key": auth["pocket_consumer_key"],
        "access_token": auth["pocket_access_token"],
        "actions": json.dumps(
            [
                {
                    "action": "tags_add",
                    "item_id": item_id,
                    "tags": top_category,
                }
            ]
        ),
    }

    # print(args)
    response = requests.get("https://getpocket.com/v3/send", args)
    print ("result {}".format(response.text))
    # Extend the items with synced=1
    db["auto_tags"].update(
        item_id, {"synced": 1}
    )


def categorize_item(item, categorize_url, save_html):
    # assign resolve_url to either resolved_url or given_url
    resolved_url = item.get("resolved_url", item.get("given_url"))

    if (resolved_url is None):
        return {
            "error": True,
            "categorization": {
                "item_id": item["item_id"],
                "error": "No resolved_url or given_url",
            }
        }

    req = False
    err = False
    html = False

    try:
        # Fetch the content of the page to save it in the database
        req = requests.get(resolved_url, timeout=10)
        html = req.text
        if req.status_code != 200:
            err = "Status " + str(req.status_code) + " " + html
    except Exception as inst:
        err = str(inst)
        print(err)

    if err:
        return {
            "error": True,
            "categorization": {
                "item_id": item["item_id"],
                "error": err
            }
        }

    print("Received {} chars from {}".format(str(len(html)), resolved_url))

    if save_html:
        # Save html to a file, using an escaped version of resolve_url
        # as the filename
        # Save html to a file using a cleaned up version of the url
        valid_chars = '-_.() abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
        filename = save_html + "/" +''.join(c for c in resolved_url.replace("/", "_") if c in valid_chars)
        os.makedirs(os.path.dirname(filename), exist_ok=True)

        with open(filename, "w") as f:
            f.write(html)
    
    scores = None
    embeddings = None
    process_time = time.time()

    if not categorize_url:
        website = Webpage(item["resolved_url"])
        website.html = html
        scores, embeddings = model.predict(website)
        process_time = time.time() - process_time
        print("Predicted locally in {:.2f} seconds".format(process_time))
    else:
        try:
            # Send the request to the homepage2vec server
            req = requests.post(categorize_url,
                headers={
                    'accept': 'application/json',
                    'Content-Type': 'application/json',
                    'Authorization': 'Bearer 1234',
                },
                json={
                    "url": resolved_url,
                    "html": html
                })
            if req.status_code != 200:
                err = "Status " + str(req.status_code) + " " + req.text
        except Exception as inst:
            err = str(inst)
            print(err)

        if err:
            return {
                "error": True,
                "categorization": {
                    "item_id": item["item_id"],
                    "error": err
                }
            }

        process_time = time.time() - process_time
        print("Predicted remotely in {:.2f} seconds".format(process_time))
        json = req.json()
        scores = json["scores"]
        embeddings = json["embeddings"]

    # Given "scores" as a generator that looks like {"Arts": 0.6156846880912781, "Business": 0.3619343638420105, "Computers": 0.8148682117462158, "Games": 0.28710833191871643, "Health": 0.4017010033130646, "Home": 0.22346019744873047, "Kids_and_Teens": 0.306125283241272, "News": 0.7160046696662903, "Recreation": 0.2587287724018097, "Reference": 0.6425570249557495, "Science": 0.7425054311752319, "Shopping": 0.17683619260787964, "Society": 0.6040355563163757, "Sports": 0.08852018415927887}
    # Return a list of categories that have a score of 0.5 or higher
    # e.g. ["Arts", "Computers", "News", "Reference", "Science", "Society"]
    likely_categories = [k for k, v in scores.items() if v >= 0.5]
    top_category = max(scores, key=scores.get)

    categorization = {
        "item_id": item["item_id"],
        "error": None,
        "html": html,
        "html_md5": hashlib.md5(html.encode("utf-8")).hexdigest(),  
        "likely_categories": likely_categories,
        "top_category": top_category,
        "scores": scores,
        "embeddings": embeddings,
        "process_time": process_time,
        "created_at": datetime.datetime.now(),
        "synced": False,
    }
    print("Top category for {} (item id {}): {}".format(resolved_url, item["item_id"], top_category))

    return {
        "error": False,
        "categorization": categorization
    }

def transform(item):
    for key in (
        "item_id",
        "resolved_id",
        "favorite",
        "status",
        "time_added",
        "time_updated",
        "time_read",
        "time_favorited",
        "is_article",
        "is_index",
        "has_video",
        "has_image",
        "word_count",
        "time_to_read",
        "listen_duration_estimate",
    ):
        if key in item:
            item[key] = int(item[key])

    for key in ("time_read", "time_favorited"):
        if key in item and not item[key]:
            item[key] = None


def ensure_fts(db):
    if "items_fts" not in db.table_names():
        db["items"].enable_fts(["resolved_title", "excerpt"], create_triggers=True)


def fetch_stats(auth):
    response = requests.get(
        "https://getpocket.com/v3/stats",
        {
            "consumer_key": auth["pocket_consumer_key"],
            "access_token": auth["pocket_access_token"],
        },
    )
    response.raise_for_status()
    return response.json()


class FetchItems:
    def __init__(
        self, auth, since=None, page_size=500, sleep=2, retry_sleep=3, record_since=None
    ):
        self.auth = auth
        self.since = since
        self.page_size = page_size
        self.sleep = sleep
        self.retry_sleep = retry_sleep
        self.record_since = record_since

    def __iter__(self):
        offset = 0
        retries = 0
        while True:
            args = {
                "consumer_key": self.auth["pocket_consumer_key"],
                "access_token": self.auth["pocket_access_token"],
                "sort": "oldest",
                "state": "all",
                "detailType": "complete",
                "count": self.page_size,
                "offset": offset,
            }
            if self.since is not None:
                args["since"] = self.since
            response = requests.get("https://getpocket.com/v3/get", args)
            if response.status_code == 503 and retries < 5:
                print("Got a 503, retrying...")
                retries += 1
                time.sleep(retries * self.retry_sleep)
                continue
            else:
                retries = 0
            response.raise_for_status()
            page = response.json()
            items = list((page["list"] or {}).values())
            next_since = page["since"]
            if self.record_since and next_since:
                self.record_since(next_since)
            if not items:
                break
            yield from items
            offset += self.page_size
            if self.sleep:
                time.sleep(self.sleep)
