# hitomi

This is a tool for downloading galleries from [hitomi.la](https://hitomi.la), with some library management capabilities.

## Installation

```bash
git clone https://github.com/sern/hitomi
cd hitomi
pip install .
```

Check successful installation by running `hitomi --help`


## Usage

### First-time Setup

`cd` into a directory that will become your hentai library, then run `hitomi --init`

```bash
HENTAI_DIR=~/Pictures/hentai
mkdir -p $HENTAI_DIR && cd $HENTAI_DIR
hitomi --init
```

It is recommended to set this directory as an environmental variable `$HENTAI_DIR`, so that later you can run `hitomi` anywhere without `cd`ing into this directory.

```bash
echo "export HENTAI_DIR=$HENTAI_DIR" >> ~/.bashrc
```

### Download

Download a gallery:

```bash
hitomi 'https://hitomi.la/doujinshi/犬山たまきが馬並みちんぽなんかに負けるわけないだろ!-日本語-1890998.html'
```
You may need to single-quote the URL in case it contains characters that can be interpreted by the shell.

## Details

