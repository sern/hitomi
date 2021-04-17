#!/usr/bin/env python3
import json
import logging
import os
import re
import urllib
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path

import lxml.etree as le
import requests
import yaml
from pathvalidate import sanitize_filename

J = 16  # number of threads

logger = logging.getLogger(__file__)
handler = logging.StreamHandler()
formatter = logging.Formatter("%(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)
logger.setLevel(logging.DEBUG)

HENTAI_DIR = os.environ.get("HENTAI_DIR")
if HENTAI_DIR:
    logger.info(f"cd into {HENTAI_DIR}")
    os.chdir(HENTAI_DIR)
else:
    logger.info("HENTAI_DIR variable not set, using the current directory")

PROJECT_DIR = os.getcwd()

TRANSLATIONS_CHANGED = 0

yaml.Dumper.ignore_aliases = lambda *args: True


def yaml_dump(obj, fn):
    with open(fn, "w") as f:
        yaml.dump(obj, f, allow_unicode=True)


# TODO: def update_info.yml


def init_directory():
    Path("_data").mkdir(exist_ok=True)
    Path("tags").mkdir(exist_ok=True)
    Path("authors").mkdir(exist_ok=True)
    Path("groups").mkdir(exist_ok=True)
    Path("series").mkdir(exist_ok=True)
    Path("characters").mkdir(exist_ok=True)

    Path("authors.yml").touch(exist_ok=True)
    Path("groups.yml").touch(exist_ok=True)
    Path("tags.yml").touch(exist_ok=True)
    Path("series.yml").touch(exist_ok=True)
    Path("characters.yml").touch(exist_ok=True)


AUTHORS, GROUPS, SERIES, CHARACTERS, TAGS = ({}, {}, {}, {}, {})
AUTHORS_F = "authors.yml"
GROUPS_F = "groups.yml"
SERIES_F = "series.yml"
CHARACTERS_F = "characters.yml"
TAGS_F = "tags.yml"
ATTRIBUTES_AND_FILES = [
    (AUTHORS, AUTHORS_F),
    (GROUPS, GROUPS_F),
    (SERIES, SERIES_F),
    (CHARACTERS, CHARACTERS_F),
    (TAGS, TAGS_F),
]


def load_translations():
    global ATTRIBUTES_AND_FILES
    for attr_dic, file in ATTRIBUTES_AND_FILES:
        with open(file) as f:
            content = yaml.safe_load(f)
            if content:
                attr_dic.update(content)


def query_translation(dic, key, query):
    global TRANSLATIONS_CHANGED
    val = input(query)
    dic[key] = val
    TRANSLATIONS_CHANGED += 1
    return val


def save_translations():
    global TRANSLATIONS_CHANGED, ATTRIBUTES_AND_FILES
    if TRANSLATIONS_CHANGED > 0:
        for attr_dic, file in ATTRIBUTES_AND_FILES:
            yaml_dump(attr_dic, file)


def subdomain_from_galleryid(g, number_of_frontends):
    o = g % number_of_frontends
    return chr(97 + o)


def subdomain_from_url(url, base):
    number_of_frontends = 3
    _b = 16

    r = re.compile(r"/[0-9a-f]/([0-9a-f]{2})/")
    m = r.findall(url)
    if len(m) == 0:
        return "a"

    try:
        g = int(m[0], 16)
        if g < 0x30:
            number_of_frontends = 2
        if g < 0x09:
            g = 1
        retval = subdomain_from_galleryid(g, number_of_frontends) + base
    except ValueError:
        pass

    return retval


def url_from_url(url, base):
    return re.sub(
        r"//..?\.hitomi\.la/", "//" + subdomain_from_url(url, base) + ".hitomi.la/", url
    )


def full_path_from_hash(hash):
    if len(hash) < 3:
        return hash
    return re.sub(r"^.*(..)(.)$", r"\2/\1/", hash) + hash


def url_from_hash(_gallery_id, file, dir, ext):
    ext = ext or dir or file["name"].split(".")[-1]
    dir = "images" if dir == "jpg" else dir
    return (
        "https://a.hitomi.la/"
        + dir
        + "/"
        + full_path_from_hash(file["hash"])
        + "."
        + ext
    )


def url_from_url_from_hash(galleryid, file, dir, ext, base):
    return url_from_url(url_from_hash(galleryid, file, dir, ext), base)


def make_source_url(galleryid, file, type):
    return url_from_url_from_hash(
        galleryid, file, type, None, "b" if type == "jpg" else "a"
    )


def get_info_from_gallery_id(gid):
    js = requests.get(f"https://ltn.hitomi.la/galleries/{gid}.js").text

    info = json.loads(js[js.find("{") :])

    files = info["files"]
    for file in files:

        if file["hasavif"]:
            type = "avif"
        elif file["haswebp"]:
            type = "webp"
        else:
            type = "jpg"

        file["url"] = make_source_url(gid, file, type)
        file["name"] = file["name"].split(".")[0] + f".{type}"

    return info


def gid_from_url(url):
    PATTERN = r"https://hitomi.la/[a-z]+/(?P<name>.+)-(?P<lang>[^-]+)-(?P<gid>\d+).html"
    return re.match(PATTERN, url).group("gid")


def check_title(title):
    r = input(
        f"{title}\nIs the title correct? (Input the correct title if it's not correct)\n"
    )
    return r or title


class Api(object):
    def __init__(self, url):
        self.url = urllib.parse.unquote(url)
        gid = gid_from_url(self.url)
        self.gid = gid
        self.metadata = {"source": {"website": "hitomi", "id": gid, "url": self.url}}
        self.parse_gallery_page()
        logger.info("Getting metadata...")
        info = get_info_from_gallery_id(gid)
        self.info = info
        self.metadata["title"] = check_title(
            info.get("japanese_title") or info.get("title") or input("Title?\n")
        )
        self.s = requests.Session()
        self.s.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:87.0) Gecko/20100101 Firefox/87.0",
                "Accept": "image/avif,image/webp,*/*",
                "Accept-Language": "ja,en-US;q=0.7,en;q=0.3",
                "Referer": f"https://hitomi.la/reader/${gid}.html",
                "Connection": "keep-alive",
                "TE": "Trailers",
            }
        )
        self.dirname = (
            sanitize_filename(self.metadata["title"]) + f'|{self.metadata["language"]}'
        )
        dir = os.path.join("_data", self.dirname)

        def is_duplicate(dir):
            if os.path.exists(dir):
                with open(os.path.join(dir, "_info.yml")) as f:
                    if yaml.safe_load(f)["source"]["url"] == self.url:
                        if (
                            input(
                                f"Do you want to repeat downloading {self.url}? (y/n; default is y)"
                            )[0]
                            == "n"
                        ):
                            return True

        if is_duplicate(dir):
            i = 0
            while True:
                i += 1
                d = dir + "_" + str(i)
                if not is_duplicate(d):
                    self.dirname += "_" + str(i)
                    break
        self.dirname_from_project_root = os.path.join("_data", self.dirname)

        Path(self.dirname_from_project_root).mkdir(exist_ok=True)

    def parse_gallery_page(self):
        global AUTHORS, TAGS, GROUPS, SERIES, CHARACTERS
        r = requests.get(self.url)
        assert r.status_code == 200
        html = le.HTML(r.text)

        def ask_for_original_names(lst, dic, ty):
            for i in range(len(lst)):
                q = lst[i]
                v = dic.get(q)
                if not v:
                    v = query_translation(
                        dic, q, f"What is the original name of {ty} '{q}'?"
                    )
                lst[i] = v

        authors = [a.text for a in html.xpath("//h2//li/a")]
        self.metadata["authors-raw"] = deepcopy(authors)
        ask_for_original_names(authors, AUTHORS, "author")
        self.metadata["authors"] = authors

        groups, type, language, series, characters, tags = [
            [a.text for a in field.xpath(".//a")]
            for field in html.xpath('//div[@class="gallery-info"]//tr')
        ]

        self.metadata["groups-raw"] = deepcopy(groups)
        ask_for_original_names(groups, GROUPS, "group")
        self.metadata["groups"] = groups

        self.metadata["original"] = True if type[0].strip() == "original" else False
        self.metadata["language"] = language[0].strip()

        self.metadata["series-raw"] = deepcopy(series)
        ask_for_original_names(series, SERIES, "series")
        self.metadata["series"] = series

        self.metadata["characters-raw"] = deepcopy(characters)
        ask_for_original_names(characters, CHARACTERS, "character")
        self.metadata["characters"] = characters

        tags = [re.match(r"([a-z ]+)([♀♂])?", tag).group(1).rstrip() for tag in tags]
        self.metadata["tags-raw"] = tags

    def write_metadata(self):
        with open("_info.yml", "w") as f:
            yaml.dump(self.metadata, f, allow_unicode=True)

    def download(self, metadata_only=False):
        os.chdir(self.dirname_from_project_root)

        self.write_metadata()
        if not metadata_only:
            # download
            with ThreadPoolExecutor(max_workers=J) as executor:
                [
                    executor.submit(self.download_single, file)
                    for file in self.info["files"]
                ]

        logger.info(f"Finished downloading to: {os.getcwd()}")
        os.chdir(PROJECT_DIR)
        self.update_symlinks()

    def download_single(self, file):
        fn = file["name"]
        if os.path.exists(fn) and os.path.getsize(fn) > 0:
            return
        logger.info("Downloading: " + fn)
        r = self.s.get(file["url"])
        if r.status_code != 200:
            raise Exception("Failed to download: " + file["url"])
        with open(fn, "wb") as f:
            f.write(r.content)

    def update_symlinks(self):
        update_symlinks_authors(self.dirname, self.metadata["authors"])
        update_symlinks_groups(self.dirname, self.metadata["groups"])
        update_symlinks_tags(
            self.dirname, [TAGS[t] for t in self.metadata["tags-raw"] if TAGS.get(t)]
        )
        update_symlinks_series(self.dirname, self.metadata["series"])
        update_symlinks_characters(self.dirname, self.metadata["characters"])


def update_symlinks_all():
    for hentai in os.listdir("_data"):
        if hentai == ".DS_Store":
            continue
        with open(os.path.join("_data", hentai, "_info.yml")) as f:
            metadata = yaml.safe_load(f)
        update_symlinks_authors(hentai, metadata["authors"])
        update_symlinks_groups(hentai, metadata["groups"])
        update_symlinks_series(hentai, metadata["series"])
        update_symlinks_characters(hentai, metadata["characters"])
        update_symlinks_tags(
            hentai, [TAGS[t] for t in metadata["tags-raw"] if TAGS.get(t)]
        )
    pass


def update_symlinks_generic(dirname, attr, values):
    """dirname should be without "_data"; wd should be at project root"""
    for v in values:
        p = Path(os.path.join(attr, v))
        p.mkdir(exist_ok=True)
        dst = os.path.join(p, dirname)
        if os.path.exists(dst):
            os.unlink(dst)
        os.symlink(os.path.join("..", "..", "_data", dirname), dst)


def update_symlinks_tags(dirname, tags):
    update_symlinks_generic(dirname, "tags", tags)


def update_symlinks_authors(dirname, authors):
    update_symlinks_generic(dirname, "authors", authors)


def update_symlinks_groups(dirname, groups):
    update_symlinks_generic(dirname, "groups", groups)


def update_symlinks_series(dirname, series):
    update_symlinks_generic(dirname, "series", series)


def update_symlinks_characters(dirname, characters):
    update_symlinks_generic(dirname, "characters", characters)


def main():
    # import sys

    # args = sys.argv
    # cmd = args[1]

    # if cmd == "init":
    #     init_directory()
    # else:
    #     load_translations()
    #     if cmd == "update-links":
    #         update_symlinks_all()
    #     elif cmd == "debug":
    #         print(ATTRIBUTES_AND_FILES)
    #     elif cmd == "dl" or args.cmd == "download":
    #         metadata_only = False
    #         if args[2] == "--metadata-only":
    #             metadata_only = True
    #             url = args[3]
    #         else:
    #             url = args[2]
    #         api = Api(args.url)
    #         api.download(metadata_only)
    #     save_translations()

    import argparse

    parser = argparse.ArgumentParser(description="Download a gallery from hitomi.la")
    # subparser = parser.add_subparsers(dest="cmd")
    parser.add_argument(
        "url", metavar="URL", type=str, nargs="?", help="Gallery URL",
    )
    parser.add_argument(
        "-m",
        "--metadata-only",
        action="store_true",
        default=False,
        help="Download only metadata",
    )
    parser.add_argument(
        "--update-links", action="store_true", default=False, help="Update symlinks",
    )
    parser.add_argument(
        "--init", action="store_true", default=False, help="init directory"
    )
    parser.add_argument(
        "--debug", action="store_true", default=False,
    )

    args = parser.parse_args()

    if args.init:
        init_directory()
    else:
        load_translations()
        if args.debug:
            print(ATTRIBUTES_AND_FILES)
        elif args.update_links:
            update_symlinks_all()
        else:
            api = Api(args.url)
            api.download(args.metadata_only)

    save_translations()
