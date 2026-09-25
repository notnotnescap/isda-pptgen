"""Generate a worship service presentation from a YAML config file."""

import argparse
import datetime
from importlib import import_module
from pathlib import Path

from pptx import Presentation

try:
    yaml = import_module("yaml")
except ModuleNotFoundError:
    yaml = None

import json
import os
import urllib.parse
import urllib.request

from isda_pptgen.builder import (
    delete_template_slides,
    insert_end_slide,
    insert_external_song_by_id,
    insert_hymn,
    insert_membership_transfer_slide,
    insert_scripture_slide,
    insert_sermon_title_slide,
    insert_start_slide,
    insert_thithes_and_offerings_slides,
    insert_title_with_logo_slide,
    insert_video_slide,
)
from isda_pptgen.merge import merge_pptx
from isda_pptgen.ytdl import burn_subtitles, download_youtube_video

CONFIG_TEMPLATE = Path(__file__).with_name("build_ws.template.yml")
DEFAULT_CONFIG = Path(__file__).with_name("build_ws.yml")


def load_yaml_config(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(
            f"Config file not found at {path}. Copy the template from {CONFIG_TEMPLATE} and update its values."
        )
    if yaml is None:
        raise ImportError(
            "PyYAML is required to load the YAML config file. Install it with 'uv sync' or pip."
        )
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def parse_optional_int(value):
    """Parse a value that may be empty, an int, or an external hymn id like 'ext_1'.

    Returns:
        None for empty values, an int for numeric inputs, or the original
        'ext_...' string for external hymn identifiers.
    """
    if value is None or value == "":
        return None
    if isinstance(value, str) and value.startswith("ext_"):
        return value
    return int(value)


def parse_int_list(value):
    """Parse a value into a list of hymn identifiers.

    The returned list may contain ints and/or external hymn id strings like
    'ext_1'. Accepts None, int, comma-separated strings, or lists.
    """
    if value is None:
        return []

    def _convert_item(item):
        if item is None:
            return None
        s = str(item).strip()
        if s == "":
            return None
        if s.startswith("ext_"):
            return s
        return int(s)

    if isinstance(value, int):
        return [value]
    if isinstance(value, str):
        stripped = value.strip()
        if stripped == "":
            return []
        parts = [p.strip() for p in stripped.split(",")]
        result = []
        for p in parts:
            if p == "":
                continue
            result.append(_convert_item(p))
        return result
    if isinstance(value, list):
        result = []
        for item in value:
            conv = _convert_item(item)
            if conv is not None:
                result.append(conv)
        return result
    raise ValueError(f"Unable to convert {value!r} to a list of ints or external ids")


def get_bible_verses(reference, version="kjv"):
    """
    Fetches Bible verses from bible-api.com.
    Note: Free APIs often lack modern copyrighted versions like NIV,
    so 'kjv', 'web', 'bbe' are the typical available options.
    """
    if not reference:
        return (("1", "No reference provided."),)

    url = f"https://bible-api.com/{urllib.parse.quote(reference)}?translation={version}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode())
            return tuple(
                (str(v["verse"]), v["text"].strip()) for v in data.get("verses", [])
            )
    except Exception as e:
        print(f"Error fetching {reference}: {e}")
        return (("?", "Error fetching scripture."),)


def get_filename(date: datetime.date) -> str:
    """Generates a filename based on the date."""
    day = date.day
    if 11 <= (day % 100) <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")

    month_year = date.strftime(" %B %Y")
    return f"ISDA Church Slides - {day}{suffix}{month_year}"


def build_presentation(config: dict):
    raw_date = config["date"]
    if isinstance(raw_date, datetime.date):
        date = raw_date
    else:
        date = datetime.date.fromisoformat(str(raw_date))

    mission_spotlight_url = config.get("mission_spotlight_url", "") or ""
    song_service_hymns = parse_int_list(config.get("song_service_hymns"))
    call_to_worship_scripture_reference = (
        config.get("call_to_worship_scripture_reference", "") or ""
    )
    opening_song_hymn = parse_optional_int(config.get("opening_song_hymn"))
    childrens_story_ppt = config.get("childrens_story_ppt", "") or ""
    thermometers_slides = config.get("thermometers_slides", "") or ""
    unallocated_offerings = config.get("unallocated_offerings", "") or ""
    special_item_video_url = config.get("special_item_video_url", "") or ""
    scripture_reading_reference = config.get("scripture_reading_reference", "") or ""
    sermon_title = config.get("sermon_title", "") or ""
    sermon_slides = config.get("sermon_slides", "") or ""
    preacher = config.get("preacher", "") or ""
    meditation_video_url = config.get("meditation_video_url", "") or ""
    closing_song_hymn = parse_optional_int(config.get("closing_song_hymn"))
    membership_transfers = config.get("membership_transfers", []) or []

    filename = get_filename(date)
    presentation = Presentation("assets/template.pptx")
    media_dir = f"media/{date}"
    os.makedirs(media_dir, exist_ok=True)
    os.makedirs("media/global_announcements", exist_ok=True)

    def clear_program_media():
        import glob

        for ext in ["*.png", "*.srt", "*.mp4"]:
            for file in glob.glob(os.path.join(media_dir, ext)):
                os.remove(file)

    def insert_song(pres: Presentation, song_ref):
        if isinstance(song_ref, str) and song_ref.startswith("ext_"):
            insert_external_song_by_id(pres, int(song_ref.replace("ext_", "")))
        else:
            insert_hymn(pres, song_ref)

    def insert_video_if_available(
        pres: Presentation, video_path: str, thumbnail_path: str, caption: str = ""
    ):
        """Insert a video slide only if the media files exist on disk.

        When a video URL is configured but the media was never downloaded
        (e.g. 'Download Media' is off), skip the slide with a warning instead
        of failing the whole build.
        """
        if os.path.exists(video_path) and os.path.exists(thumbnail_path):
            insert_video_slide(pres, video_path, thumbnail_path, caption)
        else:
            print(
                f"Warning: video not found at {video_path} (media not downloaded). "
                "Skipping its slide — enable 'Download Media' to include it."
            )

    # Downloading and preparing media
    download_media = config.get("download_media", False)
    if download_media:
        clear_program_media()
        if mission_spotlight_url != "":
            download_youtube_video(
                mission_spotlight_url,
                output_dir=media_dir,
                filename="mission-spotlight",
                download_subtitles=True,
            )
            import glob
            import shutil

            srt_files = glob.glob(f"{media_dir}/mission-spotlight*.srt")
            if srt_files:
                burn_subtitles(
                    f"{media_dir}/mission-spotlight.mp4",
                    srt_files[0],
                    f"{media_dir}/mission-spotlight-subbed.mp4",
                )
            else:
                shutil.copy(
                    f"{media_dir}/mission-spotlight.mp4",
                    f"{media_dir}/mission-spotlight-subbed.mp4",
                )

        if special_item_video_url != "":
            download_youtube_video(
                special_item_video_url,
                output_dir=media_dir,
                filename="special-item",
                download_subtitles=False,
            )
        if meditation_video_url != "":
            download_youtube_video(
                meditation_video_url,
                output_dir=media_dir,
                filename="meditation",
                download_subtitles=False,
            )

    # fetch scripture
    print("Fetching scripture...")
    call_to_worship_scripture = get_bible_verses(
        call_to_worship_scripture_reference, version="kjv"
    )
    scripture_reading = get_bible_verses(scripture_reading_reference, version="kjv")

    print("Building presentation...")
    # start slides
    insert_start_slide(presentation, date)
    insert_title_with_logo_slide(
        presentation, "Sabbath School Offering & Mission Spotlight"
    )

    # mission spotlight
    if mission_spotlight_url != "":
        insert_video_if_available(
            presentation,
            f"{media_dir}/mission-spotlight-subbed.mp4",
            f"{media_dir}/mission-spotlight.png",
            "Mission Spotlight",
        )

    # song service
    insert_title_with_logo_slide(presentation, "Song Service")
    for hymn_number in song_service_hymns:
        insert_song(presentation, hymn_number)

    # announcements
    # insert_welcome_and_announcements_slide(presentation)
    # insert_title_with_logo_slide(presentation, "Welcome and Announcements") # does not include animation

    # Process both global announcements and program-specific announcements
    # for ann_dir in ["media/global_announcements", f"{media_dir}/announcements"]:
    #     if os.path.exists(ann_dir):
    #         images = tuple(sorted([os.path.join(ann_dir, f) for f in os.listdir(ann_dir) if f.lower().endswith(('.png', '.jpg', '.jpeg'))]))
    #         if images:
    #             insert_images(presentation, images)
    merge_pptx(presentation, "media/announcements.pptx")

    # membership transfers
    if membership_transfers:
        insert_title_with_logo_slide(presentation, "Membership Transfers")
        for transfer in membership_transfers:
            insert_membership_transfer_slide(
                presentation,
                in_or_out=transfer.get("in_or_out"),
                reading=transfer.get("reading"),
                name=transfer.get("name"),
                church=transfer.get("church"),
            )

    # opening song
    insert_title_with_logo_slide(presentation, "Call to Worship")
    insert_scripture_slide(
        presentation, call_to_worship_scripture_reference, call_to_worship_scripture
    )
    insert_title_with_logo_slide(presentation, "Opening Song")
    if opening_song_hymn is not None:
        insert_song(presentation, opening_song_hymn)

    # intercessory prayer
    insert_title_with_logo_slide(presentation, "Intercessory Prayer")

    # children's story
    insert_title_with_logo_slide(presentation, "Children's Story")
    if childrens_story_ppt != "":
        merge_pptx(presentation, childrens_story_ppt)

    # tithes and offerings
    insert_title_with_logo_slide(presentation, "Tithes and Offerings")
    if thermometers_slides != "":
        merge_pptx(presentation, thermometers_slides)
    insert_thithes_and_offerings_slides(presentation, unallocated_offerings)

    # special music
    insert_title_with_logo_slide(presentation, "Special Music")
    if special_item_video_url != "":
        insert_video_if_available(
            presentation,
            f"{media_dir}/special-item.mp4",
            f"{media_dir}/special-item.png",
        )

    # scripture reading
    insert_title_with_logo_slide(presentation, "Scripture Reading")
    insert_scripture_slide(presentation, scripture_reading_reference, scripture_reading)

    # sermon
    insert_sermon_title_slide(presentation, sermon_title, preacher)
    # insert_title_with_logo_slide(presentation, f"Sermon : {sermon_title}") # should include preacher aswell
    if sermon_slides != "":
        merge_pptx(presentation, sermon_slides)

    insert_title_with_logo_slide(presentation, "Meditation")
    if meditation_video_url != "":
        insert_video_if_available(
            presentation,
            f"{media_dir}/meditation.mp4",
            f"{media_dir}/meditation.png",
        )

    # closing song
    insert_title_with_logo_slide(presentation, "Closing Song")
    if closing_song_hymn is not None:
        insert_song(presentation, closing_song_hymn)

    # closing
    insert_title_with_logo_slide(presentation, "Closing Prayer")
    insert_title_with_logo_slide(presentation, "Closing Remarks")
    insert_end_slide(presentation)

    delete_template_slides(presentation)
    presentation.save(f"output/{filename}.pptx")
    print(f"Done! Presentation generated successfully at output/{filename}.pptx")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate a worship service presentation from a YAML config file."
    )
    parser.add_argument(
        "--config",
        default=DEFAULT_CONFIG,
        help="Path to the YAML configuration file",
    )
    args = parser.parse_args()

    build_presentation(load_yaml_config(Path(args.config)))
