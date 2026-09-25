import difflib
import json
from pathlib import Path

import streamlit as st

st.set_page_config(page_title="ISDA Song Manager", layout="wide")
st.title("Song Manager")

HYMNS_FILE = Path("assets/hymns.json")
EXT_SONGS_FILE = Path("assets/external_songs.json")


def load_data(file_path):
    if not file_path.exists():
        return []
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_data(file_path, data):
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def normalize_name(name):
    """Lowercase and strip punctuation/spacing for fuzzy title matching."""
    return "".join(c for c in name.lower() if c.isalnum() or c.isspace()).strip()


def find_similar_songs(name, songs, threshold=0.6):
    """Return songs whose title resembles `name`, best matches first."""
    norm = normalize_name(name)
    if not norm:
        return []

    results = []
    for s in songs:
        sname = normalize_name(s.get("name", ""))
        if not sname:
            continue
        if norm == sname or (len(norm) >= 3 and (norm in sname or sname in norm)):
            score = 1.0
        else:
            score = difflib.SequenceMatcher(None, norm, sname).ratio()
        if score >= threshold:
            results.append((score, s))
    results.sort(key=lambda x: -x[0])
    return results


def render_similar_song(score, song, source_label):
    """Show a similar song with a quick way to view its lyrics."""
    name = song.get("name", "Untitled")
    sid = song.get("id", "")
    author = song.get("author") or ""
    header = f"{source_label} · {sid} - {name}"
    if author:
        header += f" ({author})"
    header += f"  — match {score:.0%}"
    with st.expander(header):
        lyrics = song.get("lyrics", [])
        if not lyrics:
            st.caption("(no lyrics)")
        for block in lyrics:
            label = block.get("label", "")
            btype = block.get("type", "")
            tag = " ".join(part for part in (btype, label) if part)
            st.markdown(f"**{tag}**" if tag else "")
            st.write(block.get("text", ""))


st.sidebar.header("Select Source")
source_type = st.sidebar.radio("Source", ["Hymns", "External Songs"])

current_file = HYMNS_FILE if source_type == "Hymns" else EXT_SONGS_FILE
songs_data = load_data(current_file)

# Load both groups so we can warn about duplicate titles across them.
hymns_data = load_data(HYMNS_FILE)
ext_songs_data = load_data(EXT_SONGS_FILE)

# Sorting by ID if present
songs_data = sorted(songs_data, key=lambda x: x.get("id", 0))

# Sidebar: Select/Create Song
song_options = ["--- Create New Song ---"] + [
    f"{s.get('id', '')} - {s.get('name', 'Untitled')}" for s in songs_data
]
selected_song_str = st.sidebar.selectbox("Select a song", song_options)

if selected_song_str == "--- Create New Song ---":
    st.header("Create New Song")
    new_id = st.number_input(
        "ID", value=max([s.get("id", 0) for s in songs_data] + [0]) + 1, step=1
    )
    new_name = st.text_input("Name")
    new_author = st.text_input("Author", value="")
    new_key = st.text_input("Key", value="")

    # Warn about existing songs with a similar title as the user types.
    if new_name.strip():
        similar_hymns = find_similar_songs(new_name, hymns_data)
        similar_ext = find_similar_songs(new_name, ext_songs_data)
        if similar_hymns or similar_ext:
            st.warning("Similar songs already exist — check before creating:")
            for score, song in similar_hymns:
                render_similar_song(score, song, "Hymn")
            for score, song in similar_ext:
                render_similar_song(score, song, "External")

    if st.button("Create"):
        new_song = {
            "id": new_id,
            "name": new_name,
            "author": new_author if new_author else None,
            "key": new_key if new_key else None,
            "lyrics": [],
        }
        songs_data.append(new_song)
        save_data(current_file, songs_data)
        st.success(f"Created {new_name}!")
        st.rerun()

else:
    # Find selected song
    sel_id = int(selected_song_str.split(" - ")[0])
    song_idx = next(
        (i for i, s in enumerate(songs_data) if s.get("id") == sel_id), None
    )

    if song_idx is not None:
        song = songs_data[song_idx]
        st.header(f"Edit: {song.get('name')}")

        col1, col2, col3 = st.columns(3)
        with col1:
            song_name = st.text_input(
                "Name", value=song.get("name", ""), key=f"name_{sel_id}"
            )
        with col2:
            song_author = st.text_input(
                "Author",
                value=song.get("author", "") or "",
                key=f"author_{sel_id}",
            )
        with col3:
            song_key = st.text_input(
                "Key", value=song.get("key", "") or "", key=f"key_{sel_id}"
            )

        st.subheader("Lyrics")
        lyrics = song.get("lyrics", [])
        updated_lyrics = []

        tab_editor, tab_quick = st.tabs(["Block Editor", "Quick Import"])

        with tab_editor:
            for i, block in enumerate(lyrics):
                with st.expander(
                    f"Block {i + 1}: {block.get('label', '')} ({block.get('type', '')})",
                    expanded=True,
                ):
                    bc1, bc2 = st.columns([1, 1])
                    with bc1:
                        b_type = st.text_input(
                            f"Type (verse/refrain/etc) {i}",
                            value=block.get("type", ""),
                            key=f"type_{sel_id}_{i}",
                        )
                    with bc2:
                        b_label = st.text_input(
                            f"Label (1, Chorus, etc) {i}",
                            value=block.get("label", ""),
                            key=f"label_{sel_id}_{i}",
                        )

                    b_text = st.text_area(
                        f"Text {i}",
                        value=block.get("text", ""),
                        key=f"text_{sel_id}_{i}",
                        height=250,
                    )

                    if st.button(f"Remove Block {i + 1}", key=f"rm_{sel_id}_{i}"):
                        continue  # Skip appending this block

                    updated_lyrics.append(
                        {"type": b_type, "label": b_label, "text": b_text}
                    )

            if st.button("Add New Block"):
                updated_lyrics.append(
                    {"type": "verse", "label": str(len(updated_lyrics) + 1), "text": ""}
                )
                song["lyrics"] = updated_lyrics
                songs_data[song_idx] = song
                save_data(current_file, songs_data)
                st.rerun()

        with tab_quick:
            st.info(
                "Paste lyrics below. Use tags like `#verse 1` or `#refrain Chorus` above each paragraph."
            )
            quick_text = st.text_area(
                "Quick Import Lyrics",
                height=300,
                key=f"quick_import_text_{sel_id}",
            )

            if st.button("Import & Replace Lyrics", type="secondary"):
                if quick_text.strip():
                    new_blocks = []
                    current_block = None

                    for line in quick_text.split("\n"):
                        line_stripped = line.strip()
                        if line_stripped.startswith("#"):
                            # Save previous block if exists
                            if current_block and current_block["text"].strip():
                                current_block["text"] = current_block["text"].strip()
                                new_blocks.append(current_block)

                            # Parse new block tag
                            tag_parts = line_stripped[1:].strip().split(" ", 1)
                            b_type = tag_parts[0]
                            b_label = tag_parts[1] if len(tag_parts) > 1 else ""

                            current_block = {
                                "type": b_type,
                                "label": b_label,
                                "text": "",
                            }
                        else:
                            if not current_block:
                                # Start a default block if no tag was provided and this is text
                                current_block = {
                                    "type": "verse",
                                    "label": "1",
                                    "text": "",
                                }
                            if line_stripped or current_block["text"]:
                                current_block["text"] += line + "\n"

                    if current_block and current_block["text"].strip():
                        current_block["text"] = current_block["text"].strip()
                        new_blocks.append(current_block)

                    song["lyrics"] = new_blocks
                    songs_data[song_idx] = song
                    save_data(current_file, songs_data)
                    st.success("Lyrics imported successfully!")
                    st.rerun()

        st.markdown("---")

        c_save, c_del = st.columns(2)
        with c_save:
            if st.button("Save Changes", type="primary"):
                song["name"] = song_name
                song["author"] = song_author if song_author else None
                song["key"] = song_key if song_key else None
                song["lyrics"] = updated_lyrics
                songs_data[song_idx] = song
                save_data(current_file, songs_data)
                st.success("Changes saved!")
                st.rerun()

        with c_del:
            if st.button("Delete Song", type="primary"):
                songs_data.pop(song_idx)
                save_data(current_file, songs_data)
                st.warning("Song deleted!")
                st.rerun()
