# -*- coding: utf-8 -*-
#  This file is part of Headphones.
#
#  Headphones is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  Headphones is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with Headphones.  If not, see <http://www.gnu.org/licenses/>.

import os
import re
import shutil
import sys
import tempfile
import time
import unicodedata
from contextlib import contextmanager
from datetime import datetime, date
from fnmatch import fnmatch
from functools import cmp_to_key
from glob import glob
from operator import itemgetter

from beets import logging as beetslogging
from mediafile import MediaFile, FileTypeError, UnreadableFileError
from six import text_type
from unidecode import unidecode

import headphones


# Modified from https://github.com/Verrus/beets-plugin-featInTitle
RE_FEATURING = re.compile(r"[fF]t\.|[fF]eaturing|[fF]eat\.|\b[wW]ith\b|&|vs\.")

RE_CD_ALBUM = re.compile(r"\(?((CD|disc)\s*[0-9]+)\)?", re.I)
RE_CD = re.compile(r"^(CD|dics)\s*[0-9]+$", re.I)

def cmp(x, y):
    """
    Replacement for built-in function cmp that was removed in Python 3

    Compare the two objects x and y and return an integer according to
    the outcome. The return value is negative if x < y, zero if x == y
    and strictly positive if x > y.

    https://portingguide.readthedocs.io/en/latest/comparisons.html#the-cmp-function
    """
    if x is None and y is None:
        return 0
    elif x is None:
        return -1
    elif y is None:
        return 1
    else:
        return (x > y) - (x < y)

def multikeysort(items, columns):
    comparers = [
        ((itemgetter(col[1:].strip()), -1) if col.startswith('-') else (itemgetter(col.strip()), 1))
        for col in columns]

    def comparer(left, right):
        for fn, mult in comparers:
            result = cmp(fn(left), fn(right))
            if result:
                return mult * result
        else:
            return 0

    return sorted(items, key=cmp_to_key(comparer))


def checked(variable):
    if variable:
        return 'Checked'
    else:
        return ''


def radio(variable, pos):
    if variable == pos:
        return 'Checked'
    else:
        return ''


def latinToAscii(unicrap):
    """
    From couch potato
    """
    xlate = {
        0xc0: 'A', 0xc1: 'A', 0xc2: 'A', 0xc3: 'A', 0xc4: 'A', 0xc5: 'A',
        0xc6: 'Ae', 0xc7: 'C',
        0xc8: 'E', 0xc9: 'E', 0xca: 'E', 0xcb: 'E', 0x86: 'e', 0x39e: 'E',
        0xcc: 'I', 0xcd: 'I', 0xce: 'I', 0xcf: 'I',
        0xd0: 'Th', 0xd1: 'N',
        0xd2: 'O', 0xd3: 'O', 0xd4: 'O', 0xd5: 'O', 0xd6: 'O', 0xd8: 'O',
        0xd9: 'U', 0xda: 'U', 0xdb: 'U', 0xdc: 'U',
        0xdd: 'Y', 0xde: 'th', 0xdf: 'ss',
        0xe0: 'a', 0xe1: 'a', 0xe2: 'a', 0xe3: 'a', 0xe4: 'a', 0xe5: 'a',
        0xe6: 'ae', 0xe7: 'c',
        0xe8: 'e', 0xe9: 'e', 0xea: 'e', 0xeb: 'e', 0x0259: 'e',
        0xec: 'i', 0xed: 'i', 0xee: 'i', 0xef: 'i',
        0xf0: 'th', 0xf1: 'n',
        0xf2: 'o', 0xf3: 'o', 0xf4: 'o', 0xf5: 'o', 0xf6: 'o', 0xf8: 'o',
        0xf9: 'u', 0xfa: 'u', 0xfb: 'u', 0xfc: 'u',
        0xfd: 'y', 0xfe: 'th', 0xff: 'y',
        0xa1: '!', 0xa2: '{cent}', 0xa3: '{pound}', 0xa4: '{currency}',
        0xa5: '{yen}', 0xa6: '|', 0xa7: '{section}', 0xa8: '{umlaut}',
        0xa9: '{C}', 0xaa: '{^a}', 0xab: '<<', 0xac: '{not}',
        0xad: '-', 0xae: '{R}', 0xaf: '_', 0xb0: '{degrees}',
        0xb1: '{+/-}', 0xb2: '{^2}', 0xb3: '{^3}', 0xb4: "'",
        0xb5: '{micro}', 0xb6: '{paragraph}', 0xb7: '*', 0xb8: '{cedilla}',
        0xb9: '{^1}', 0xba: '{^o}', 0xbb: '>>',
        0xbc: '{1/4}', 0xbd: '{1/2}', 0xbe: '{3/4}', 0xbf: '?',
        0xd7: '*', 0xf7: '/'
    }

    r = ''
    for i in unicrap:
        if ord(i) in xlate:
            r += xlate[ord(i)]
        elif ord(i) >= 0x80:
            pass
        else:
            r += str(i)
    return r


def convert_milliseconds(ms):
    seconds = ms / 1000
    gmtime = time.gmtime(seconds)
    if seconds > 3600:
        minutes = time.strftime("%H:%M:%S", gmtime)
    else:
        minutes = time.strftime("%M:%S", gmtime)

    return minutes


def convert_seconds(s):
    gmtime = time.gmtime(s)
    if s > 3600:
        minutes = time.strftime("%H:%M:%S", gmtime)
    else:
        minutes = time.strftime("%M:%S", gmtime)

    return minutes


def today():
    return date.isoformat(date.today())


def now():
    now = datetime.now()
    return now.strftime("%Y-%m-%d %H:%M:%S")


def is_valid_date(d):
    if not d:
        return False
    else:
        return bool(re.match(r'\d{4}-\d{2}-\d{2}', d))


def age(d):
    '''Requires a valid date'''
    if not is_valid_date(d):
        return -1
    else:
        delta = date.today() - date.fromisoformat(d)
        return delta.days



def bytes_to_mb(bytes):
    mb = int(bytes) / 1048576
    size = '%.1f MB' % mb
    return size


def mb_to_bytes(mb_str):
    result = re.search('^(\d+(?:\.\d+)?)\s?(?:mb)?', mb_str, flags=re.I)
    if result:
        return int(float(result.group(1)) * 1048576)


def piratesize(size):
    split = size.split(" ")
    factor = float(split[0])
    unit = split[1].upper()

    if unit == 'MIB':
        size = factor * 1048576
    elif unit == 'MB':
        size = factor * 1000000
    elif unit == 'GIB':
        size = factor * 1073741824
    elif unit == 'GB':
        size = factor * 1000000000
    elif unit == 'KIB':
        size = factor * 1024
    elif unit == 'KB':
        size = factor * 1000
    elif unit == "B":
        size = factor
    else:
        size = 0

    return size


def pattern_substitute(pattern, dic, normalize=False):
    """
    Execute path rendering/substitution based on replacement dictionary
    e.g. pattern = $Artist/$Album
         dic = {Artist: 'My artist', Album: 'My album'}
         returns My artist/My album
    """
    from headphones import pathrender
    if not pattern:
        return ''

    if normalize:
        new_dic = {}
        for i, j in dic.items():
            if j is not None:
                try:
                    if sys.platform == 'darwin':
                        j = unicodedata.normalize('NFD', j)
                    else:
                        j = unicodedata.normalize('NFC', j)
                except TypeError:
                    j = unicodedata.normalize('NFC',
                        j.decode(headphones.SYS_ENCODING, 'replace'))
            new_dic[i] = j
        dic = new_dic
    return pathrender.render(pattern, dic)[0]


def replace_all(text, dic):
    if not text:
        return ''

    for i, j in dic.items():
        text = text.replace(i, j)
    return text


def replace_illegal_chars(string, type="file"):
    if type == "file":
        string = re.sub('[\?"*:|<>/]', '_', string)
    if type == "folder":
        string = re.sub('[:\?<>"|*]', '_', string)
    return string


_CN_RE1 = re.compile(r'[^\w]+', re.UNICODE)
_CN_RE2 = re.compile(r'[\s_]+', re.UNICODE)


_XLATE_GRAPHICAL_AND_DIACRITICAL = {
    # Translation table.
    # Covers the following letters, for which NFD fails because of lack of
    # combining character:
    # ©ª«®²³¹»¼½¾ÆÐØÞßæðøþĐđĦħıĲĳĸĿŀŁłŒœŦŧǄǅǆǇǈǉǊǋǌǤǥǱǲǳȤȥ. This
    # includes also some graphical symbols which can be easily replaced and
    # usually are written by people who don't have appropriate keyboard layout.
    '©': '(C)', 'ª': 'a.', '«': '<<', '®': '(R)', '²': '2', '³': '3',
    '¹': '1', '»': '>>', '¼': ' 1/4 ', '½': ' 1/2 ', '¾': ' 3/4 ',
    'Æ': 'AE', 'Ð': 'D', 'Ø': 'O', 'Þ': 'Th', 'ß': 'ss', 'æ': 'ae',
    'ð': 'd', 'ø': 'o', 'þ': 'th', 'Đ': 'D', 'đ': 'd', 'Ħ': 'H',
    'ħ': 'h', 'ı': 'i', 'Ĳ': 'IJ', 'ĳ': 'ij', 'ĸ': 'q', 'Ŀ': 'L',
    'ŀ': 'l', 'Ł': 'L', 'ł': 'l', 'Œ': 'OE', 'œ': 'oe', 'Ŧ': 'T',
    'ŧ': 't', 'Ǆ': 'DZ', 'ǅ': 'Dz', 'Ǉ': 'LJ', 'ǈ': 'Lj',
    'ǉ': 'lj', 'Ǌ': 'NJ', 'ǋ': 'Nj', 'ǌ': 'nj',
    'Ǥ': 'G', 'ǥ': 'g', 'Ǳ': 'DZ', 'ǲ': 'Dz', 'ǳ': 'dz',
    'Ȥ': 'Z', 'ȥ': 'z', '№': 'No.',
    'º': 'o.',        # normalize Nº abbrev (popular w/ classical music),
                       # this is 'masculine ordering indicator', not degree
}

_XLATE_SPECIAL = {
    # Translation table.
    # Cover additional special characters processing normalization.
    "'": '',         # replace apostrophe with nothing
    "’": '',         # replace musicbrainz style apostrophe with nothing
    '&': ' and ',     # expand & to ' and '
}

_XLATE_MUSICBRAINZ = {
    # Translation table for Musicbrainz.
    "…": '...',     # HORIZONTAL ELLIPSIS (U+2026)
    "’": "'",       # APOSTROPHE (U+0027)
    "‐": "-",       # EN DASH (U+2013)
}


def _translate(s, dictionary):
    # type: (basestring,Mapping[basestring,basestring])->basestring
    return ''.join(dictionary.get(x, x) for x in s)


_COMBINING_RANGES = (
    (0x0300, 0x036f),   # Combining Diacritical Marks
    (0x1ab0, 0x1aff),   # Combining Diacritical Marks Extended
    (0x20d0, 0x20ff),   # Combining Diacritical Marks for Symbols
    (0x1dc0, 0x1dff)    # Combining Diacritical Marks Supplement
)


def _is_unicode_combining(u):
    # type: (unicode)->bool
    """
    Check if input unicode is combining diacritical mark.
    """
    i = ord(u)
    for r in _COMBINING_RANGES:
        if r[0] <= i <= r[1]:
            return True
    return False


def _transliterate(u, xlate):
    # type: (unicode)->unicode
    """
    Perform transliteration using the specified dictionary
    """
    u = unicodedata.normalize('NFD', u)
    u = ''.join(['' if _is_unicode_combining(x) else x for x in u])
    u = _translate(u, xlate)
    # at this point output is either unicode, or plain ascii
    return str(u)


def clean_name(s):
    # type: (basestring)->unicode
    """Remove non-alphanumeric characters from the string, perform
    normalization and substitution of some special characters; coalesce spaces.
    :param s: string to clean up, possibly unicode one.
    :return: cleaned-up version of input string.
    """
    if not isinstance(s, str):
        # ignore extended chars if someone was dumb enough to pass non-ascii
        # narrow string here, use only unicode for meaningful texts
        u = str(s, 'ascii', 'replace')
    else:
        u = s
    # 1. don't bother doing normalization NFKC, rather transliterate
    # using special translation table
    u = _transliterate(u, _XLATE_GRAPHICAL_AND_DIACRITICAL)
    # 2. normalize NFKC the result
    u = unicodedata.normalize('NFKC', u)
    # 3. translate spacials
    u = _translate(u, _XLATE_SPECIAL)
    # 4. replace any non-alphanumeric character sequences by spaces
    u = _CN_RE1.sub(' ', u)
    # 5. coalesce interleaved space/underscore sequences
    u = _CN_RE2.sub(' ', u)
    # 6. trim
    u = u.strip()
    # 7. lowercase
    u = u.lower()
    return u


def clean_musicbrainz_name(s, return_as_string=True):
    # type: (basestring)->unicode
    """Substitute special Musicbrainz characters.
    :param s: string to clean up, probably unicode.
    :return: cleaned-up version of input string.
    """
    if not isinstance(s, str):
        u = str(s, 'ascii', 'replace')
    else:
        u = s
    u = _translate(u, _XLATE_MUSICBRAINZ)
    if return_as_string:
        return u.encode('utf-8')
    else:
        return u


def cleanTitle(title):
    title = re.sub('[\.\-\/\_]', ' ', title).lower()

    # Strip out extra whitespace
    title = ' '.join(title.split())

    title = title.title()

    return title


def split_path(f):
    """
    Split a path into components, starting with the drive letter (if any). Given
    a path, os.path.join(*split_path(f)) should be path equal to f.
    """

    components = []
    drive, path = os.path.splitdrive(f)

    # Strip the folder from the path, iterate until nothing is left
    while True:
        path, folder = os.path.split(path)

        if folder:
            components.append(folder)
        else:
            if path:
                components.append(path)

            break

    # Append the drive (if any)
    if drive:
        components.append(drive)

    # Reverse components
    components.reverse()

    # Done
    return components


def expand_subfolders(f):
    """
    Try to expand a given folder and search for subfolders containing media
    files. This should work for discographies indexed per album in the same
    root, possibly with folders per CD (if any).

    This algorithm will return nothing if the result is only one folder. In this
    case, normal post processing will be better.
    """

    from headphones import logger

    # Find all folders with media files in them
    media_folders = []

    for root, dirs, files in os.walk(f):
        for file in files:
            extension = os.path.splitext(file)[1].lower()[1:]

            if extension in headphones.MEDIA_FORMATS:
                if root not in media_folders:
                    media_folders.append(root)

    # Stop here if nothing found
    if len(media_folders) == 0:
        return

    # Split into path components
    media_folders = [split_path(media_folder) for media_folder in media_folders]

    # Correct folder endings such as CD1 etc.
    for index, media_folder in enumerate(media_folders):
        if RE_CD.match(media_folder[-1]):
            media_folders[index] = media_folders[index][:-1]

    # Verify the result by computing path depth relative to root.
    path_depths = [len(media_folder) for media_folder in media_folders]
    difference = max(path_depths) - min(path_depths)

    if difference > 0:
        logger.info(
            f"Found {len(media_folders)} media folders, but depth difference between lowest and deepest media folder is {difference} (expected zero). If this is a discography or a collection of albums, make sure albums are per folder.")

        # While already failed, advice the user what he could try. We assume the
        # directory may contain separate CD's and maybe some extra's. The
        # structure may look like X albums at same depth, and (one or more)
        # extra folders with a higher depth.
        extra_media_folders = [media_folder[:min(path_depths)] for media_folder in media_folders if
                               len(media_folder) > min(path_depths)]
        extra_media_folders = list(
            set([os.path.join(*media_folder) for media_folder in extra_media_folders]))

        logger.info(
            f"Please look at the following folder(s), since they cause the depth difference: {extra_media_folders}")
        return

    # Convert back to paths and remove duplicates, which may be there after
    # correcting the paths
    media_folders = list(set([os.path.join(*media_folder) for media_folder in media_folders]))

    # Don't return a result if the number of subfolders is one. In this case,
    # this algorithm will not improve processing and will likely interfere
    # with other attempts such as MusicBrainz release group IDs.
    if len(media_folders) == 1:
        logger.debug("Did not expand subfolder, as it resulted in one folder.")
        return

    logger.debug(f"Expanded subfolders in folder: {media_folders}")
    return media_folders


def path_match_patterns(path, patterns):
    """
    Check if a path matches one or more patterns. The whole path will be
    matched be matched against the patterns.
    """

    for pattern in patterns:
        if fnmatch(path, pattern):
            return True

    # No match
    return False


def path_filter_patterns(paths, patterns, root=''):
    """
    Scan for ignored paths based on glob patterns. Note that the whole path
    will be matched, therefore paths should only contain the relative paths.

    The root is optional, and only used for producing meaningful debug info.
    """

    from headphones import logger

    ignored = 0

    for path in paths[:]:
        if path_match_patterns(path, patterns):
            logger.debug(f"Path ignored by pattern: {os.path.join(root, path)}")

            ignored += 1
            paths.remove(path)

    # Return number of ignored paths
    return ignored


def extract_data(s):
    s = s.replace('_', ' ')

    # headphones default format
    pattern = re.compile(r'(?P<name>.*?)\s\-\s(?P<album>.*?)\s[\[\(](?P<year>.*?)[\]\)]',
                         re.VERBOSE)
    match = pattern.match(s)

    if match:
        name = match.group("name")
        album = match.group("album")
        year = match.group("year")
        return (name, album, year)

    # Gonna take a guess on this one - might be enough to search on mb
    pat = re.compile(r"(?P<name>.*?)\s*-\s*(?P<album>[^\[(-]*)")

    match = pat.match(s)
    if match:
        name = match.group("name")
        album = match.group("album")
        year = None
        return (name, album, year)

    else:
        return (None, None, None)


def extract_metadata(f):
    """
    Scan all files in the given directory and decide on an artist, album and
    year based on the metadata. A decision is based on the number of different
    artists, albums and years found in the media files.
    """

    from headphones import logger

    # Walk directory and scan all media files
    results = []
    count = 0

    for root, dirs, files in os.walk(f):
        for file in files:
            # Count the number of potential media files
            extension = os.path.splitext(file)[1].lower()[1:]

            if extension in headphones.MEDIA_FORMATS:
                count += 1

            # Try to read the file info
            try:
                media_file = MediaFile(os.path.join(root, file))
            except (FileTypeError, UnreadableFileError):
                # Probably not a media file
                continue

            # Append metadata to file
            artist = media_file.albumartist or media_file.artist
            album = media_file.album
            year = media_file.year

            if artist and album and year:
                results.append((artist.lower(), album.lower(), year))

    # Verify results
    if len(results) == 0:
        logger.info("No metadata in media files found, ignoring.")
        return (None, None, None)

    # Require that some percentage of files have tags
    count_ratio = 0.75

    if count < (count_ratio * len(results)):
        logger.info(f"Counted {count} media files, but only {len(results)} have tags, ignoring.")
        return (None, None, None)

    # Count distinct values
    artists = list(set([x[0] for x in results]))
    albums = list(set([x[1] for x in results]))
    years = list(set([x[2] for x in results]))

    # Remove things such as CD2 from album names
    if len(albums) > 1:
        new_albums = list(albums)

        # Replace occurences of e.g. CD1
        for index, album in enumerate(new_albums):
            if RE_CD_ALBUM.search(album):
                old_album = new_albums[index]
                new_albums[index] = RE_CD_ALBUM.sub("", album).strip()

                logger.debug(f"Stripped album number identifier: {old_album} -> {new_albums[index]}")

        # Remove duplicates
        new_albums = list(set(new_albums))

        # Safety check: if nothing has merged, then ignore the work. This can
        # happen if only one CD of a multi part CD is processed.
        if len(new_albums) < len(albums):
            albums = new_albums

    # All files have the same metadata, so it's trivial
    if len(artists) == 1 and len(albums) == 1:
        return (artists[0], albums[0], years[0])

    # (Lots of) different artists. Could be a featuring album, so test for this.
    if len(artists) > 1 and len(albums) == 1:
        split_artists = [RE_FEATURING.split(x) for x in artists]
        featurings = [len(split_artist) - 1 for split_artist in split_artists]
        logger.info("Album seem to feature {sum(featurings)} different artists")

        if sum(featurings) > 0:
            # Find the artist of which the least splits have been generated.
            # Ideally, this should be 0, which should be the album artist
            # itself.
            artist = split_artists[featurings.index(min(featurings))][0]

            # Done
            return (artist, albums[0], years[0])

    # Not sure what to do here.
    logger.info(
        f"Found {len(artists)} artists, {len(albums)} albums and "
        f"{len(years)} years in metadata, so ignoring"
    )
    logger.debug("Artists: {artists}, Albums: {albums}, Years: {years}")

    return (None, None, None)


def get_downloaded_track_list(albumpath):
    """
     Return a list of audio files for the given directory.
     """
    downloaded_track_list = []

    for root, dirs, files in os.walk(albumpath):
        for _file in files:
            extension = os.path.splitext(_file)[1].lower()[1:]
            if extension in headphones.MEDIA_FORMATS:
                downloaded_track_list.append(os.path.join(root, _file))

    return downloaded_track_list


def preserve_torrent_directory(albumpath, forced=False, single=False):
    """
    Copy torrent directory to temp headphones_ directory to keep files for seeding.
    """
    from headphones import logger

    # Create temp dir
    if headphones.CONFIG.KEEP_TORRENT_FILES_DIR:
        tempdir = headphones.CONFIG.KEEP_TORRENT_FILES_DIR
    else:
        tempdir = tempfile.gettempdir()

    logger.info(f"Preparing to copy to a temporary directory for post processing: {albumpath}")

    try:
        file_name = os.path.basename(os.path.normpath(albumpath))
        if not single:
            prefix = "headphones_" + file_name + "_@hp@_"
        else:
            prefix = "headphones_" + os.path.splitext(file_name)[0] + "_@hp@_"
        new_folder = tempfile.mkdtemp(prefix=prefix, dir=tempdir)
    except Exception as e:
        logger.error(f"Cannot create temp directory: {tempdir}. Error: {e}")
        return None

    # Attempt to stop multiple temp dirs being created for the same albumpath
    if not forced:
        try:
            workdir = os.path.join(tempdir, prefix)
            workdir = re.sub(r'\[', '[[]', workdir)
            workdir = re.sub(r'(?<!\[)\]', '[]]', workdir)
            if len(glob(workdir + '*/')) >= 3:
                logger.error(
                    "Looks like a temp directory has previously been created "
                    "for this albumpath, not continuing "
                )
                shutil.rmtree(new_folder)
                return None
        except Exception as e:
            logger.warn(
                "Cannot determine if already copied/processed, will copy anyway. "
                f"Warning: {e}"
            )

    # Copy to temp dir
    try:
        subdir = os.path.join(new_folder, "headphones")
        logger.info(f"Copying files to {subdir}")
        if not single:
            shutil.copytree(albumpath, subdir)
        else:
            os.makedirs(subdir)
            shutil.copy(albumpath, subdir)
        # Update the album path with the new location
        return subdir
    except Exception as e:
        logger.warn(
            f"Cannot copy/move files to temp directory: {new_folder}. "
            f"Not continuing. Error: {e}"
        )
        shutil.rmtree(new_folder)
        return None


def cue_split(albumpath, keep_original_folder=False):
    """
     Attempts to check and split audio files by a cue for the given directory.
     """
    # Walk directory and scan all media files
    count = 0
    cue_count = 0
    cue_dirs = []

    for root, dirs, files in os.walk(albumpath):
        for _file in files:
            extension = os.path.splitext(_file)[1].lower()[1:]
            if extension in headphones.MEDIA_FORMATS:
                count += 1
            elif extension == 'cue':
                cue_count += 1
                if root not in cue_dirs:
                    cue_dirs.append(root)

    # Split cue
    if cue_count and cue_count >= count and cue_dirs:

        # Copy to temp directory
        if keep_original_folder:
            temppath = preserve_torrent_directory(albumpath)
            if temppath:
                cue_dirs = [cue_dir.replace(albumpath, temppath) for cue_dir in cue_dirs]
                albumpath = temppath
            else:
                return None

        from headphones import logger, cuesplit
        logger.info("Attempting to split audio files by cue")

        cwd = os.getcwd()
        for cue_dir in cue_dirs:
            try:
                cuesplit.split(cue_dir)
            except Exception as e:
                os.chdir(cwd)
                logger.warn(f"Cue not split. Error: {e}")
                return None

        os.chdir(cwd)
        return albumpath

    return None


def extract_logline(s):
    # Default log format
    pattern = re.compile(
        r'(?P<timestamp>.*?)\s\-\s(?P<level>.*?)\s*\:\:\s(?P<thread>.*?)\s\:\s(?P<message>.*)',
        re.VERBOSE)
    match = pattern.match(s)
    if match:
        timestamp = match.group("timestamp")
        level = match.group("level")
        thread = match.group("thread")
        message = match.group("message")
        return (timestamp, level, thread, message)
    else:
        return None


def extract_song_data(s):
    from headphones import logger

    # headphones default format
    pattern = re.compile(r'(?P<name>.*?)\s\-\s(?P<album>.*?)\s\[(?P<year>.*?)\]', re.VERBOSE)
    match = pattern.match(s)

    if match:
        name = match.group("name")
        album = match.group("album")
        year = match.group("year")
        return (name, album, year)
    else:
        logger.info(f"Couldn't parse {s} into a valid default format")

    # newzbin default format
    pattern = re.compile(r'(?P<name>.*?)\s\-\s(?P<album>.*?)\s\((?P<year>\d+?\))', re.VERBOSE)
    match = pattern.match(s)
    if match:
        name = match.group("name")
        album = match.group("album")
        year = match.group("year")
        return (name, album, year)
    else:
        logger.info(f"Couldn't parse {s} into a valid Newbin format")
        return (name, album, year)


def smartMove(src, dest, delete=True):
    from headphones import logger

    source_dir = os.path.dirname(src)
    filename = os.path.basename(src)
    source_path = os.path.join(source_dir, filename)
    dest_path = os.path.join(dest, filename)

    if os.path.isfile(dest_path):
        logger.info(f"Destination file exists: {dest_path}")
        title = os.path.splitext(filename)[0]
        ext = os.path.splitext(filename)[1]
        i = 1
        while True:
            newfile = title + '(' + str(i) + ')' + ext
            if os.path.isfile(os.path.join(dest, newfile)):
                i += 1
            else:
                logger.info(f"Renaming to {newfile}")
                try:
                    os.rename(src, os.path.join(source_dir, newfile))
                    filename = newfile
                except Exception as e:
                    logger.warn(f"Error renaming {src}: {e}")
                break

    if delete:
        try:
            logger.info('Moving "%s" to "%s"', source_path, dest_path)
            shutil.move(source_path, dest_path)
        except Exception as e:
            exists = os.path.exists(dest_path)
            if exists and os.path.getsize(source_path) == os.path.getsize(dest_path):
                logger.warn(
                    f"Successfully moved {filename}, but something went wrong: {e}"
                )
                os.unlink(source_path)
            else:
                # remove faultly copied file
                if exists:
                    os.unlink(dest_path)
                raise
    else:
        try:
            logger.info(f"Copying {source_path} to {dest_path}")
            shutil.copy(source_path, dest_path)
            return True
        except Exception as e:
            logger.warn(f"Error copying {filename}: {e}") 


def walk_directory(basedir, followlinks=True):
    """
    Enhanced version of 'os.walk' where symlink directores are traversed, but
    with care. In case a folder is already processed, don't traverse it again.
    """

    from . import logger

    # Add the base path, because symlinks poiting to the basedir should not be
    # traversed again.
    traversed = [os.path.abspath(basedir)]

    def _inner(root, directories, files):
        for directory in directories:
            path = os.path.join(root, directory)

            if followlinks and os.path.islink(path):
                real_path = os.path.abspath(os.readlink(path))

                if real_path in traversed:
                    logger.debug(
                        f"Skipping {path} since it is a symlink to "
                        f"{real_path}, which is already visited."
                    )
                else:
                    traversed.append(real_path)

                    for args in os.walk(real_path):
                        for result in _inner(*args):
                            yield result

        # Pass on actual result
        yield root, directories, files

    # Start traversing
    for args in os.walk(basedir):
        for result in _inner(*args):
            yield result


#########################
# Sab renaming functions #
#########################

# TODO: Grab config values from sab to know when these options are checked. For now we'll just iterate through all combinations


def sab_replace_dots(name):
    return name.replace('.', ' ')


def sab_replace_spaces(name):
    return name.replace(' ', '_')


def sab_sanitize_foldername(name):
    """ Return foldername with dodgy chars converted to safe ones
        Remove any leading and trailing dot and space characters
    """
    CH_ILLEGAL = r'\/<>?*|"'
    CH_LEGAL = r'++{}!@#`'

    FL_ILLEGAL = CH_ILLEGAL + ':\x92"'
    FL_LEGAL = CH_LEGAL + "-''"

    if not name:
        return

    name = unidecode(name)

    lst = []
    for ch in name.strip():
        if ch in FL_ILLEGAL:
            ch = FL_LEGAL[FL_ILLEGAL.find(ch)]
            lst.append(ch)
        else:
            lst.append(ch)
    name = ''.join(lst)

    name = name.strip('. ')
    if not name:
        name = 'unknown'

    # maxlen = cfg.folder_max_length()
    # if len(name) > maxlen:
    #    name = name[:maxlen]

    return name


def split_string(mystring, splitvar=','):
    mylist = []
    for each_word in mystring.split(splitvar):
        mylist.append(each_word.strip())
    return mylist


def create_https_certificates(ssl_cert, ssl_key):
    """
    Create a pair of self-signed HTTPS certificares and store in them in
    'ssl_cert' and 'ssl_key'. Method assumes pyOpenSSL is installed.

    This code is stolen from SickBeard (http://github.com/midgetspy/Sick-Beard).
    """

    from headphones import logger

    from OpenSSL import crypto
    from certgen import createKeyPair, createCertRequest, createCertificate, \
        TYPE_RSA, serial

    # Create the CA Certificate
    cakey = createKeyPair(TYPE_RSA, 2048)
    careq = createCertRequest(cakey, CN="Certificate Authority")
    cacert = createCertificate(careq, (careq, cakey), serial,
                               (0, 60 * 60 * 24 * 365 * 10))  # ten years

    pkey = createKeyPair(TYPE_RSA, 2048)
    req = createCertRequest(pkey, CN="Headphones")
    cert = createCertificate(req, (cacert, cakey), serial,
                             (0, 60 * 60 * 24 * 365 * 10))  # ten years

    # Save the key and certificate to disk
    try:
        with open(ssl_key, "w") as fp:
            fp.write(crypto.dump_privatekey(crypto.FILETYPE_PEM, pkey))
        with open(ssl_cert, "w") as fp:
            fp.write(crypto.dump_certificate(crypto.FILETYPE_PEM, cert))
    except IOError as e:
        logger.error(f"Error creating SSL key and certificate: e")
        return False

    return True


class BeetsLogCapture(beetslogging.Handler):

    def __init__(self):
        beetslogging.Handler.__init__(self)
        self.messages = []

    def emit(self, record):
        self.messages.append(text_type(record.msg))


@contextmanager
def capture_beets_log(logger='beets'):
    capture = BeetsLogCapture()
    log = beetslogging.getLogger(logger)
    log.addHandler(capture)
    try:
        yield capture.messages
    finally:
        log.removeHandler(capture)

def have_pct_have_total(db_artist):
    have_tracks = db_artist['HaveTracks'] or 0
    total_tracks = db_artist['TotalTracks'] or 0 
    have_pct = have_tracks / total_tracks if total_tracks else 0
    return (have_pct, total_tracks)

