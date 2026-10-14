# Running Tome on your Mac

This guide sets up the `tome` command-line tool on your MacBook Air (2020,
Intel Core i3, macOS Ventura 13.6). The goal is to parse your *Harry Potter*
omnibus EPUB and report back how Tome splits it into books and chapters.

It takes about 30–45 minutes, most of it waiting for downloads. You don't
need Homebrew.

**The one rule:** the book stays on your Mac. Put it only in the `library/`
folder, which git ignores. Never paste book text anywhere, including into a
chat with Claude. Chapter titles and the counts that `tome parse` prints are
fine to share.

All commands go in the **Terminal** app (Applications → Utilities →
Terminal). Copy each grey block, paste it into Terminal and press Return.
Lines starting with `#` are comments, and pasting them does no harm.

---

## Step 1. Install Apple's Command Line Tools (for `git`)

```sh
xcode-select --install
```

- A dialog appears. Click **Install** and accept the licence. It takes 5–20
  minutes.
- If Terminal says `command line tools are already installed`, that's fine.
  Go on to the check below.

**Check:**

```sh
git --version
```

Success looks like `git version 2.x.x (Apple Git-...)`. If the install dialog
appears again instead, let it finish and re-run the check.

## Step 2. Install uv (it installs Python for you)

[uv](https://docs.astral.sh/uv/) manages Python and Tome's dependencies. Its
official installer is:

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh
```

It installs `uv` into `~/.local/bin` and adds that folder to your `PATH` in
`~/.zshrc`. **Quit Terminal (⌘Q) and open it again** so the change takes
effect. Alternatively, run `source $HOME/.local/bin/env`.

**Check:**

```sh
uv --version
```

Success looks like `uv 0.x.y (...)`. If you get `uv: command not found`, see
[Troubleshooting](#troubleshooting).

Now install Python 3.12. **Use 3.12 specifically, not a newer version.** On an
Intel Mac the embedding library (onnxruntime) only exists for Python 3.10–3.13.
Python 3.12 is what Tome is tested with.

```sh
uv python install 3.12
```

Success looks like `Installed Python 3.12.x in ...`.

## Step 3. Get the code

This puts the code in a `code` folder in your home folder. Avoid Desktop,
Documents and Downloads, because macOS asks for extra permissions there.

```sh
mkdir -p ~/code
cd ~/code
git clone https://github.com/plangdon84/Tome.git tome
cd tome
git switch claude/mac-setup-guide
```

- If the repository is private, git asks for your GitHub username and a
  password. The password must be a **personal access token**, not your GitHub
  password. Create one at GitHub → Settings → Developer settings → Personal
  access tokens, with read access to this repository.
- Success: the last line says `Switched to a new branch 'claude/mac-setup-guide'`
  (or `branch ... set up to track ...`).

From here on, every command assumes you're in `~/code/tome`. If you open a new
Terminal window, run `cd ~/code/tome` first.

## Step 4. Install Tome's dependencies

```sh
uv sync --python 3.12
```

This creates a private Python environment in `.venv/` and downloads about 45
packages. Nothing is installed system-wide.

**Check:**

```sh
uv run python -V
uv run python -c "import onnxruntime; print(onnxruntime.__version__)"
uv run tome --help
```

Success looks like this:

- `Python 3.12.x`
- `1.23.2`. On Intel Macs, Tome deliberately uses this older onnxruntime,
  because it's the last release built for Intel Macs.
- a help screen listing `corpus`, `parse`, `pack`, `search` and so on.

## Step 5 (optional but recommended). Confirm the install

Run the test suite:

```sh
uv run pytest
```

Success: the last line reads something like `131 passed, 6 skipped`. The
exact numbers may differ, but there should be **no** `failed` or `error`.
Skips are normal.

Then try a known-good, public-domain book:

```sh
uv run tome corpus fetch monte-cristo
uv run tome parse corpus/monte-cristo.epub
```

Success looks like:

```
The Count of Monte Cristo: 1 book(s)
  b1 'The Count of Monte Cristo': 117 chapters, 1638 passages, 463,021 words (...)
```

The number that matters is **117 chapters**. If you see it, the parser works
on your Mac.

## Step 6. Put your EPUB in `library/`

Create the folder and copy the book in. Give it a simple name without spaces,
because it makes the commands easier. The examples use `harry-potter.epub`.
Change the first path to wherever your file actually is. You can drag the
file from Finder onto the Terminal window to paste its path.

```sh
mkdir -p library
cp ~/Downloads/YOUR-OMNIBUS-FILE.epub library/harry-potter.epub
ls library
```

Success: `ls` shows `harry-potter.epub`.

Make sure git ignores it:

```sh
git status --short
```

This should print **nothing** about `library/` or `.epub`. If it lists your
book, stop and tell Claude before doing anything else.

If macOS asks "Terminal would like to access files in your Downloads folder",
click **OK**.

## Step 7. First parse: the default (one book)

```sh
uv run tome parse library/harry-potter.epub
```

Without a layout file, Tome treats the whole file as **one book**. Expect
something like:

```
Harry Potter: The Complete Collection: 1 book(s)
  b1 '...': 199 chapters, ... passages, ... words (...)
  hint: The TOC has 7 top-level groups ('...', '...', ...). If these are separate books (an omnibus), add a layout file with split = "toc".
```

Your title and numbers will differ. **Copy the whole output into a note. You
will send it back.** The important things are:

- the chapter count;
- any `warning:` lines;
- whether a `hint:` line appears, and how many groups it mentions.

## Step 8. Second parse: split into books

Create the layout file. It must have the same name as the EPUB, with
`.layout.toml` in place of `.epub`:

```sh
printf 'split = "toc"\n' > library/harry-potter.layout.toml
cat library/harry-potter.layout.toml
```

`cat` should print `split = "toc"`.

> To edit this file later, use `nano library/harry-potter.layout.toml` (save
> with Ctrl-O then Return, quit with Ctrl-X). **Don't use TextEdit.** It turns
> `"` into curly quotes, which breaks the file.

Now parse again, listing every chapter, and save the output in `library/` so
it stays private:

```sh
uv run tome parse library/harry-potter.epub --chapters | tee library/parse-report.txt
```

You'll see one summary line per book, and each is followed by its chapters:

```
Harry Potter: The Complete Collection: 7 book(s)
  b1 '...Philosopher's Stone': 17 chapters, ... passages, ... words (...)
     ch1    The Boy Who Lived  (... passages)
     ...
  b2 ...
```

To check it, compare against the real chapter counts:

| Book | Chapters |
|---|---|
| 1. Philosopher's (Sorcerer's) Stone | 17 |
| 2. Chamber of Secrets | 18 |
| 3. Prisoner of Azkaban | 22 |
| 4. Goblet of Fire | 37 |
| 5. Order of the Phoenix | 38 |
| 6. Half-Blood Prince | 30 |
| 7. Deathly Hallows | 36, plus the epilogue (37 entries) |

Then go to [Step 9](#step-9-what-to-send-back), or to [If the split isn't
right](#if-the-split-isnt-right) if anything looks off.

## Step 9. What to send back

Send these. **Don't send any book text.**

1. **Step 7 output (one book):** the summary line, plus all `warning:` and
   `hint:` lines.
2. **Step 8 output:**
   - the first line (`...: N book(s)`);
   - each book's summary line (`b1 '...': N chapters, N passages, N words ...`);
   - all `warning:` lines;
   - for each book, its **first and last chapter titles**.

   The whole `library/parse-report.txt` contains only titles and counts, so
   it's fine to paste too.
3. **Your verdict:**
   - Are there 7 books?
   - Do the chapter counts match the table?
   - Is anything that isn't a chapter listed as one (a map, a dedication,
     "About the Author", an extract from another book)?
   - Is any real chapter missing?
4. **Your layout file**, if you changed it from `split = "toc"`:
   `cat library/harry-potter.layout.toml`.

---

## If the split isn't right

After every change to the layout file, re-run the Step 8 command. Each fix
below is a line you add to `library/harry-potter.layout.toml` using `nano`.

### "no TOC entries with chapters at level 1; treating the EPUB as one book"

**What it means:** the table of contents (TOC) nests the books one level
deeper. For example, there's a single top entry such as "The Complete
Collection" with the seven books under it.

**Fix:** tell Tome the books are at level 2:

```toml
split = "toc"
book_level = 2
```

If level 2 also gives this warning, the TOC may be flat (see below).

### Too many books, such as 8 or 9

**What it means:** extra top-level TOC entries, like "Bonus Material" or an
excerpt from another book, are being treated as books.

**Fix:** exclude them by title. Each pattern is a regular expression matched
against TOC titles. `^` means "starts with", and case doesn't matter. An
excluded entry takes everything listed under it with it.

```toml
split = "toc"
exclude = ["^Bonus", "^Extract from"]
```

### Front matter or extras appear as chapters

For example, `ch1 Map of Hogwarts` or `ch38 About the Author`. Use the same
`exclude` list. Copy the titles exactly as Tome printed them:

```toml
exclude = ["^Map of", "^A Note from", "^About the Author"]
```

Common front matter (contents, copyright, dedication, "Also by") is already
excluded automatically.

### Book names are odd ("Part One", "Book 1" or a file name)

Give them proper names, in order:

```toml
titles = [
  "Philosopher's Stone", "Chamber of Secrets", "Prisoner of Azkaban",
  "Goblet of Fire", "Order of the Phoenix", "Half-Blood Prince", "Deathly Hallows",
]
```

### The TOC is flat (all chapters in one list, no book entries)

You see the warning above at both `book_level = 1` and `book_level = 2`, and
there was no `hint:` in Step 7. In that case, say where each book starts by
matching its first chapter's title. Replace the whole file with:

```toml
split = "manual"

[[books]]
title = "Philosopher's Stone"
start = "The Boy Who Lived$"

[[books]]
title = "Chamber of Secrets"
start = "The Worst Birthday$"

[[books]]
title = "Prisoner of Azkaban"
start = "Owl Post$"

[[books]]
title = "Goblet of Fire"
start = "The Riddle House$"

[[books]]
title = "Order of the Phoenix"
start = "Dudley Demented$"

[[books]]
title = "Half-Blood Prince"
start = "The Other Minister$"

[[books]]
title = "Deathly Hallows"
start = "The Dark Lord Ascending$"
```

How `start` works:

- Each book begins at the first TOC entry whose title matches its pattern.
- `$` means "ends here", so `"Owl Post$"` doesn't also match book 3's last
  chapter, "Owl Post Again".
- If your TOC titles look different (say `CHAPTER ONE`), copy the wording from
  your Step 7 `--chapters` output instead.

If a pattern matches nothing, Tome prints `manual layout: no TOC entry
matched the start of [...]`. Chapters before the first match are skipped,
with a warning.

---

## Troubleshooting

**`uv: command not found` after installing**
Quit Terminal fully (⌘Q) and reopen it. If it still fails, run
`source $HOME/.local/bin/env`, then try `uv --version` again. If that works,
the installer couldn't edit your shell settings, so add the line
permanently:

```sh
echo '. "$HOME/.local/bin/env"' >> ~/.zshrc
```

**Wrong Python version, or an error mentioning `onnxruntime` and `cp313`/`cp314`
("no wheels with a matching Python ABI tag")**
The environment was created with a Python newer than 3.12. Delete it and
rebuild it with 3.12:

```sh
rm -rf .venv
uv python install 3.12
uv sync --python 3.12
uv run python -V      # must print Python 3.12.x
```

Always use `uv sync --python 3.12` on this Mac. A plain `uv sync` in a fresh
folder may pick the newest Python.

**Certificate or proxy errors** (`invalid peer certificate`, `UnknownIssuer`,
`SSL`, `certificate verify failed`)
These usually mean a work VPN, antivirus or network filter intercepts HTTPS.
The simplest fix is to disconnect the VPN or use a home network. Otherwise,
tell uv to trust the certificates in the macOS keychain:

```sh
export UV_SYSTEM_CERTS=1        # on older uv versions: export UV_NATIVE_TLS=1
uv sync --python 3.12
```

If you're behind a proxy, set it first:
`export HTTPS_PROXY=http://proxy-host:port`. These `export` lines last only
for the current Terminal window.

**macOS security prompts**
- A dialog says "Terminal would like to access files in your Documents /
  Downloads / Desktop folder": click **OK**. Keeping the repo in `~/code`
  avoids most of these.
- A dialog says "cannot be opened because the developer cannot be verified":
  this shouldn't happen with the commands above. If it does, open **System
  Settings → Privacy & Security**, scroll down and click **Open Anyway** for
  that item. Don't turn Gatekeeper off.

**`git clone` asks for a password and then fails**
Use a personal access token as the password (see Step 3), or ask the repo
owner to check that your account can read the repository.

**A long red error ending in `TOMLDecodeError` or `layout split must be ...`**
The layout file has a typo. Check it with `cat library/harry-potter.layout.toml`.
Every value needs straight double quotes (`"toc"`, not `“toc”`), and lists
need square brackets and commas.

**Getting updates later**

```sh
cd ~/code/tome
git pull
uv sync --python 3.12
```
