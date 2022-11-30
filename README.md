# pocket-to-sqlite

[![PyPI](https://img.shields.io/pypi/v/pocket-to-sqlite.svg)](https://pypi.org/project/pocket-to-sqlite/)
[![Changelog](https://img.shields.io/github/v/release/dogsheep/pocket-to-sqlite?include_prereleases&label=changelog)](https://github.com/dogsheep/pocket-to-sqlite/releases)
[![Tests](https://github.com/dogsheep/pocket-to-sqlite/workflows/Test/badge.svg)](https://github.com/dogsheep/pocket-to-sqlite/actions?query=workflow%3ATest)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](https://github.com/dogsheep/pocket-to-sqlite/blob/main/LICENSE)

Create a SQLite database containing data from your [Pocket](https://getpocket.com/) account.

## How to install

    $ pip install pocket-to-sqlite

## Usage

You will need to first obtain a valid OAuth token for your Pocket account. You can do this by running the `auth` command and following the prompts:

    $ pocket-to-sqlite auth
    Visit this page and sign in with your Pocket account:

    https://getpocket.com/auth/author...

    Once you have signed in there, hit <enter> to continue
    Authentication tokens written to auth.json

Now you can fetch all of your items from Pocket like this:

    $ pocket-to-sqlite fetch pocket.db

The first time you run this command it will fetch all of your items, and display a progress bar while it does it.

On subsequent runs it will only fetch new items.

You can force it to fetch everything from the beginning again using `--all`. Use `--silent` to disable the progress bar.

## Using with Datasette

The SQLite database produced by this tool is designed to be browsed using [Datasette](https://datasette.readthedocs.io/). Use the [datasette-render-timestamps](https://github.com/simonw/datasette-render-timestamps) plugin to improve the display of the timestamp values.

## How to develop
```
python3 -m venv ./venv
source ./venv/bin/activate
pip install --editable .

# Now `pocket-to-sqlite` will refer to ./venv/bin/pocket-to-sqlite

mkdir venv/data
cd venv/data
pocket-to-sqlite auth # Twice (see note below)
pocket-to-sqlite fetch pocket.db
datasette -p 8001 -m ../../metadata.json pocket.db

pocket-to-sqlite categorize pocket.db

```

## Development notes

* `pocket-to-sqlite auth` seems to need to be run twice. First time

```
    "pocket_username": codes["username"],
KeyError: 'username'
```

and the second time it writes to auth.json

* if changing schema you can drop the table with `sqlite-utils drop-table pocket.db auto_categories`



Example queries:

```
select auto_categories.top_category, auto_categories.likely_categories, items.item_id, items.resolved_url  from auto_categories INNER JOIN items on auto_categories.item_id = items.item_id
```
```
select count(*) c, top_category from auto_categories where error is null group by top_category order by c desc
```
```
select auto_categories.top_category, auto_categories.likely_categories, items.item_id, items.resolved_url, items.resolved_title from auto_categories INNER JOIN items on auto_categories.item_id = items.item_id WHERE auto_categories.top_category="Health"
```

```
SELECT * FROM items WHERE item_id NOT IN (SELECT item_id FROM auto_categories)
```
http://localhost:3000/pocket.json?sql=select+auto_categories.top_category%2C+auto_categories.likely_categories%2C+items.item_id%2C+items.resolved_url%2C+items.resolved_title+from+auto_categories+INNER+JOIN+items+on+auto_categories.item_id+%3D+items.item_id+WHERE+auto_categories.top_category%3D%22Health%22

http://localhost:3000/pocket?sql=SELECT+COUNT%28*%29%2C+top_category+from+auto_categories+where+error+is+null+group+by+top_category#g.mark=bar&g.x_column=top_category&g.x_type=ordinal&g.y_column=COUNT(*)&g.y_type=quantitative
