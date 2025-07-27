import tkinter as tk
from tkinter import filedialog, ttk, messagebox
import json
import docx
import pygame
import difflib
import csv
import os
import threading
import time
import logging
import re
import argparse
from mismatch_detector import MismatchDetector

# --- Setup Logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    filename="review_app.log",
    filemode="w",
)
logging.info("Application starting up.")


def normalize_word(word):
    return word.lower().strip(".,;:!?\"'()[]{} ")


class AudiobookReviewApp:
    def __init__(self, root, docx_path=None, json_path=None, audio_path=None):
        self.root = root
        self.root.title("Audiobook Narrator Review Tool")
        self.root.geometry("1000x700")

        pygame.init()
        pygame.mixer.init()

        self.initial_docx_path = docx_path
        self.initial_json_path = json_path
        self.initial_audio_path = audio_path

        self.audio_file_path = None
        self.transcribed_data = []
        self.is_playing = False
        self.playback_offset = 0
        self.full_manuscript_text = ""
        self.manuscript_tokens = []
        self.word_map = {}
        self.tk_index_map = {}
        self.last_highlighted_word_index = -1
        self.after_id = None
        self.mismatches = []

        self._setup_ui()

        if all(
            [self.initial_docx_path, self.initial_json_path, self.initial_audio_path]
        ):
            self.root.after(100, self._auto_load_files)

    def _setup_ui(self):
        top_frame = ttk.Frame(self.root, padding="10")
        top_frame.pack(fill=tk.X)
        self.load_button = ttk.Button(
            top_frame, text="Load Files...", command=self.load_files
        )
        self.load_button.pack(side=tk.LEFT)
        self.loaded_files_label = ttk.Label(
            top_frame, text="Please load Manuscript, JSON, and Audio files."
        )
        self.loaded_files_label.pack(side=tk.LEFT, padx=10)

        text_frame = ttk.Frame(self.root, padding="10")
        text_frame.pack(expand=True, fill=tk.BOTH)
        self.text_widget = tk.Text(
            text_frame,
            wrap=tk.WORD,
            font=("Helvetica", 14),
            spacing1=5,
            spacing3=10,
            undo=True,
        )
        self.text_widget.pack(expand=True, fill=tk.BOTH, side=tk.LEFT)

        scrollbar = ttk.Scrollbar(text_frame, command=self.text_widget.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.text_widget.config(yscrollcommand=scrollbar.set)

        self.text_widget.tag_configure("current_word", background="lightblue")
        self.text_widget.tag_configure(
            "substitution", background="#FFDDDD"
        )  # Light Red
        self.text_widget.tag_configure(
            "deletion", background="#FFFFCC", overstrike=True
        )  # Yellow with strikethrough

        # --- CHANGE: Remapped timestamp feature to Ctrl+Click to resolve conflict ---
        self.text_widget.bind("<Control-Button-1>", self.show_timestamp_info)
        self.text_widget.bind("<Double-Button-1>", self.double_click_to_seek)

        ### --- NEW: Right panel with sensitivity slider ---
        right_panel = ttk.Frame(self.root, width=200, padding="10")
        right_panel.pack(fill=tk.Y, side=tk.RIGHT)

        ttk.Label(
            right_panel, text="Confidence Threshold:", font=("Helvetica", 10, "bold")
        ).pack(pady=(0, 5), anchor="w")
        self.sensitivity_slider = ttk.Scale(
            right_panel,
            from_=0,
            to=100,
            orient=tk.HORIZONTAL,
            # ### CHANGE: The command now calls our new function ###
            command=lambda event: self._apply_mismatch_highlights(),
        )
        self.sensitivity_slider.set(70)  # Default to 70% confidence
        self.sensitivity_slider.pack(fill=tk.X, pady=5, anchor="n")

        control_frame = ttk.Frame(self.root, padding="10")
        control_frame.pack(fill=tk.X)
        self.play_pause_button = ttk.Button(
            control_frame, text="▶ Play", command=self.toggle_play_pause
        )
        self.play_pause_button.pack(side=tk.LEFT, padx=5)
        ttk.Button(control_frame, text="⏮ 5s", command=self.rewind).pack(
            side=tk.LEFT, padx=5
        )
        ttk.Button(control_frame, text="⏭ 15s", command=self.fast_forward).pack(
            side=tk.LEFT, padx=5
        )

    def fast_forward(self, seconds=15.0):
        current_pos = (pygame.mixer.music.get_pos() / 1000.0) + self.playback_offset
        new_start = current_pos + seconds
        logging.info(f"Fast-forwarding from {current_pos:.2f}s to {new_start:.2f}s.")
        self.seek_to(new_start)

    def double_click_to_seek(self, event):
        logging.info("Double-click detected, attempting to seek.")
        click_index = self.text_widget.index(f"@{event.x},{event.y}")
        word_start_index = self.text_widget.index(f"{click_index} wordstart")
        whisper_idx = self.tk_index_map.get(word_start_index)
        if whisper_idx is not None:
            start_time = self.transcribed_data[whisper_idx]["start"]
            logging.info(
                f"User double-clicked word '{self.transcribed_data[whisper_idx]['word']}', seeking to {start_time:.2f}s"
            )
            self.seek_to(start_time)
        else:
            logging.warning(
                f"Could not find a mapped timestamp for the word at {word_start_index}."
            )

    def rewind(self, seconds=5.0):
        current_pos = (pygame.mixer.music.get_pos() / 1000.0) + self.playback_offset
        new_start = max(0, current_pos - seconds)
        logging.info(f"Rewinding from {current_pos:.2f}s to {new_start:.2f}s.")
        self.seek_to(new_start)

    def seek_to(self, time_in_seconds):
        self.reset_highlighter_state()
        pygame.mixer.music.play(start=time_in_seconds)
        self.playback_offset = time_in_seconds
        if not self.is_playing:
            self.is_playing = True
            self.play_pause_button.config(text="⏸ Pause")
            self.update_highlight()

    def _auto_load_files(self):
        logging.info("CLI arguments provided. Attempting to auto-load files.")
        self.loaded_files_label.config(text="Auto-loading files from command line...")
        self.root.update()
        try:
            self.audio_file_path = self.initial_audio_path
            self._process_files(
                self.initial_docx_path, self.initial_json_path, self.initial_audio_path
            )
            self.loaded_files_label.config(
                text=f"Ready to review: {os.path.basename(self.initial_docx_path)}"
            )
            self.load_button.config(state=tk.DISABLED)
        except Exception as e:
            logging.error(f"Failed to auto-load files from CLI: {e}", exc_info=True)
            messagebox.showerror(
                "Auto-load Error",
                f"Failed to load files from command line: {e}\n\nPlease use the 'Load Files...' button manually.\nSee review_app.log for details.",
            )
            self.loaded_files_label.config(
                text="Auto-load failed. Please load files manually."
            )

    def load_files(self):
        docx_path = filedialog.askopenfilename(
            title="1. Select Manuscript DOCX file",
            filetypes=[("Word Document", "*.docx")],
        )
        if not docx_path:
            return
        json_path = filedialog.askopenfilename(
            title="2. Select Timestamp JSON file", filetypes=[("JSON file", "*.json")]
        )
        if not json_path:
            return
        self.audio_file_path = filedialog.askopenfilename(
            title="3. Select Audio MP3 file", filetypes=[("MP3 Audio", "*.mp3")]
        )
        if not self.audio_file_path:
            return
        self.loaded_files_label.config(text="Files loaded. Processing...")
        self.root.update()
        self._process_files(docx_path, json_path, self.audio_file_path)

    def _process_files(self, docx_path, json_path, audio_path):
        try:
            logging.info(f"Processing DOCX: {docx_path}")
            self._parse_docx(docx_path)
            logging.info(f"Processing JSON: {json_path}")
            self._parse_json(json_path)
            # Create the detector and find mismatches
            detector = MismatchDetector(
                self.manuscript_tokens, self.transcribed_data, self.full_manuscript_text
            )
            self.mismatches = (
                detector.find_mismatches()
            )  # This will be our new list of mismatch objects

            # The rest of the processing continues...
            self.display_full_text()
            # The _create_word_map() for the karaoke highlighter is still needed and separate.
            self._create_word_map()
            # We will then add a new function to apply the visual highlights
            self._apply_mismatch_highlights()
            logging.info(f"Loading audio: {audio_path}")
            pygame.mixer.music.load(audio_path)
            logging.info("Processing complete. Ready for playback.")
        except Exception as e:
            logging.error(f"Failed during file processing: {e}", exc_info=True)
            messagebox.showerror(
                "Error",
                f"Failed to process files: {e}\n\nSee review_app.log for details.",
            )

    def _parse_docx(self, path):
        logging.info("Starting advanced DOCX parsing (including tables).")
        doc = docx.Document(path)
        all_text_blocks = []
        for block in doc._body._element.iterchildren():
            if isinstance(block, docx.oxml.text.paragraph.CT_P):
                para = docx.text.paragraph.Paragraph(block, doc._body)
                if para.text.strip():
                    all_text_blocks.append(para.text)
            elif isinstance(block, docx.oxml.table.CT_Tbl):
                logging.info("Found a table in the document. Extracting cell text.")
                table = docx.table.Table(block, doc._body)
                for row in table.rows:
                    for cell in row.cells:
                        if cell.text.strip():
                            all_text_blocks.append(cell.text)
        self.full_manuscript_text = "\n\n".join(all_text_blocks)
        self.manuscript_tokens = []
        for match in re.finditer(r"\b\w+\b", self.full_manuscript_text):
            self.manuscript_tokens.append(
                {"word": match.group(0), "start": match.start(), "end": match.end()}
            )
        logging.info(
            f"Advanced parse complete. Parsed {len(all_text_blocks)} total text blocks and {len(self.manuscript_tokens)} word tokens from DOCX."
        )

    def _parse_json(self, path):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.transcribed_data = data["words"]
        logging.info(
            f"Loaded {len(self.transcribed_data)} transcribed words from JSON."
        )

    def _create_word_map(self):
        logging.info("Starting alignment to create word map.")
        self.word_map = {}
        self.tk_index_map = {}
        manuscript_normalized = [
            normalize_word(token["word"]) for token in self.manuscript_tokens
        ]
        transcribed_normalized = [
            normalize_word(item["word"]) for item in self.transcribed_data
        ]
        matcher = difflib.SequenceMatcher(
            None, manuscript_normalized, transcribed_normalized, autojunk=False
        )
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal" or tag == "replace":
                for i in range(i2 - i1):
                    manuscript_index = i1 + i
                    whisper_index = j1 + i
                    token = self.manuscript_tokens[manuscript_index]
                    start_char, end_char = token["start"], token["end"]
                    tk_start_str = f"1.0 + {start_char} chars"
                    tk_end_str = f"1.0 + {end_char} chars"
                    self.word_map[whisper_index] = (tk_start_str, tk_end_str)
                    canonical_start_index = self.text_widget.index(tk_start_str)
                    self.tk_index_map[canonical_start_index] = whisper_index
        logging.info(
            f"Word map created. Mapped {len(self.word_map)} of {len(self.transcribed_data)} transcribed words."
        )

    def _format_time(self, seconds):
        if seconds is None:
            return "N/A"
        millis = int((seconds % 1) * 1000)
        return time.strftime("%H:%M:%S", time.gmtime(seconds)) + f".{millis:03d}"

    def show_timestamp_info(self, event):
        start_time, end_time = None, None
        display_text = "No timestamp available for this word."
        if self.text_widget.tag_ranges("sel"):
            sel_start, sel_end = self.text_widget.tag_ranges("sel")
            start_word_index = self.text_widget.index(f"{sel_start} wordstart")
            end_word_index = self.text_widget.index(f"{sel_end} wordend")
            start_whisper_idx = self.tk_index_map.get(start_word_index)
            end_whisper_idx = self.tk_index_map.get(
                self.text_widget.index(f"{end_word_index} wordstart")
            )
            if start_whisper_idx is not None:
                start_time = self.transcribed_data[start_whisper_idx]["start"]
            if end_whisper_idx is not None:
                end_time = self.transcribed_data[end_whisper_idx]["end"]
            display_text = f"Selection Start: {self._format_time(start_time)}\nSelection End:    {self._format_time(end_time)}"
        else:
            click_index = self.text_widget.index(f"@{event.x},{event.y}")
            word_start_index = self.text_widget.index(f"{click_index} wordstart")
            whisper_idx = self.tk_index_map.get(word_start_index)
            if whisper_idx is not None:
                word_data = self.transcribed_data[whisper_idx]
                start_time = word_data["start"]
                end_time = word_data["end"]
                display_text = f"Word Start: {self._format_time(start_time)}\nWord End:   {self._format_time(end_time)}"
        self._create_timestamp_popup(display_text)

    def _create_timestamp_popup(self, text_to_display):
        popup = tk.Toplevel(self.root)
        popup.title("Timestamp Info")
        x = self.root.winfo_x() + 150
        y = self.root.winfo_y() + 150
        popup.geometry(f"+{x}+{y}")
        popup_frame = ttk.Frame(popup, padding="10")
        popup_frame.pack()
        ttk.Label(popup_frame, text="Timestamp information:").pack(pady=5)
        text_var = tk.StringVar(value=text_to_display)
        entry = ttk.Entry(
            popup_frame, textvariable=text_var, width=40, state="readonly"
        )
        entry.pack(pady=5)
        button_frame = ttk.Frame(popup_frame)
        button_frame.pack(pady=10)

        def copy_to_clipboard():
            self.root.clipboard_clear()
            self.root.clipboard_append(text_to_display)
            logging.info(f"Copied to clipboard: '{text_to_display}'")
            copy_button.config(text="Copied!")
            copy_button.after(1500, lambda: copy_button.config(text="Copy"))

        copy_button = ttk.Button(button_frame, text="Copy", command=copy_to_clipboard)
        copy_button.pack(side=tk.LEFT, padx=5)
        close_button = ttk.Button(button_frame, text="Close", command=popup.destroy)
        close_button.pack(side=tk.LEFT, padx=5)
        popup.transient(self.root)
        popup.grab_set()
        self.root.wait_window(popup)

    def display_full_text(self):
        self.text_widget.config(state=tk.NORMAL)
        self.text_widget.delete(1.0, tk.END)
        self.text_widget.insert(tk.END, self.full_manuscript_text)
        self.text_widget.config(state=tk.DISABLED)

    def toggle_play_pause(self):
        if self.is_playing:
            pygame.mixer.music.pause()
            self.is_playing = False
            self.play_pause_button.config(text="▶ Play")
            if self.after_id:
                self.root.after_cancel(self.after_id)
            logging.info("Playback paused.")
        else:
            if self.playback_offset > 0:
                pygame.mixer.music.unpause()
            else:
                self.reset_highlighter_state()
                pygame.mixer.music.play()
            self.is_playing = True
            self.play_pause_button.config(text="⏸ Pause")
            logging.info("Playback started/resumed.")
            self.update_highlight()

    def reset_highlighter_state(self):
        self.last_highlighted_word_index = -1
        self.text_widget.tag_remove("current_word", "1.0", tk.END)

    def update_highlight(self):
        if not self.is_playing:
            return
        current_time = (pygame.mixer.music.get_pos() / 1000.0) + self.playback_offset
        for i in range(
            self.last_highlighted_word_index + 1, len(self.transcribed_data)
        ):
            word_data = self.transcribed_data[i]
            if word_data["start"] <= current_time < word_data["end"]:
                if i == self.last_highlighted_word_index:
                    break
                self.text_widget.config(state=tk.NORMAL)
                self.text_widget.tag_remove("current_word", "1.0", tk.END)
                indices = self.word_map.get(i)
                if indices:
                    tk_start, tk_end = indices
                    self.text_widget.tag_add("current_word", tk_start, tk_end)
                    self.text_widget.see(tk_start)
                self.last_highlighted_word_index = i
                self.text_widget.config(state=tk.DISABLED)
                break
        self.after_id = self.root.after(100, self.update_highlight)

    def on_closing(self):
        logging.info("Application shutting down.")
        pygame.mixer.quit()
        pygame.quit()
        if self.after_id:
            self.root.after_cancel(self.after_id)
        self.root.destroy()

    def _apply_mismatch_highlights(self):
        """
        Clears existing mismatch highlights and reapplies them based on the
        current sensitivity slider value and mismatch status.
        """
        if not self.mismatches:
            return

        logging.info("Applying mismatch highlights.")
        threshold = self.sensitivity_slider.get() / 100.0

        self.text_widget.config(state=tk.NORMAL)

        # Clear all existing mismatch tags from the text widget
        for tag in ["substitution", "deletion"]:
            self.text_widget.tag_remove(tag, "1.0", tk.END)

        # Loop through all found mismatches and apply tags if they meet the criteria
        for mismatch in self.mismatches:
            # Skip if the user has ignored this mismatch
            if mismatch["status"] == "ignored":
                continue

            # Skip if the mismatch confidence is below the slider's threshold
            if mismatch["confidence"] < threshold:
                continue

            # We can only visually highlight substitutions and deletions as they
            # map directly to text that exists in the manuscript widget.
            if mismatch["type"] == "replace" or mismatch["type"] == "delete":
                start_token_idx, end_token_idx = mismatch["manuscript_indices"]

                # Ensure the indices are valid and there's something to highlight
                if start_token_idx < end_token_idx:
                    start_char = self.manuscript_tokens[start_token_idx]["start"]
                    # The end token index is exclusive, so we use the token before it
                    end_char = self.manuscript_tokens[end_token_idx - 1]["end"]

                    tk_start = f"1.0 + {start_char} chars"
                    tk_end = f"1.0 + {end_char} chars"

                    tag_name = (
                        "substitution" if mismatch["type"] == "replace" else "deletion"
                    )
                    self.text_widget.tag_add(tag_name, tk_start, tk_end)

            elif mismatch["type"] == "insert":
                # As discussed, visually showing an insertion is complex because it means
                # adding text that isn't in the original manuscript, which would break our
                # coordinate system. For now, we log it. A future feature could be a separate
                # list view for insertions.
                logging.debug(
                    f"Skipping visual highlight for insertion: '{mismatch['narrated_text']}'"
                )

        self.text_widget.config(state=tk.DISABLED)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Audiobook Narrator Review Tool.")
    parser.add_argument("--docx", type=str, help="Path to the manuscript DOCX file.")
    parser.add_argument("--json", type=str, help="Path to the timestamp JSON file.")
    parser.add_argument("--audio", type=str, help="Path to the narration MP3 file.")
    args = parser.parse_args()
    root = tk.Tk()
    app = AudiobookReviewApp(
        root, docx_path=args.docx, json_path=args.json, audio_path=args.audio
    )
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()
