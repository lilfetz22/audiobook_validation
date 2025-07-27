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
import argparse  # ### NEW: Import argparse

# --- Setup Logging ---
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(message)s",
    filename="review_app.log",
    filemode="w",
)
logging.info("Application starting up.")


def normalize_word(word):
    return word.lower().strip(".,;:!?\"'()[]{} ")


class AudiobookReviewApp:
    # ### CHANGE: Modified __init__ to accept optional file paths ###
    def __init__(self, root, docx_path=None, json_path=None, audio_path=None):
        self.root = root
        self.root.title("Audiobook Narrator Review Tool")
        self.root.geometry("1000x700")

        pygame.init()
        pygame.mixer.init()

        # Store initial paths from CLI
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
        self.last_highlighted_word_index = -1
        self.after_id = None

        self._setup_ui()

        # ### CHANGE: Check if we should auto-load files ###
        if all(
            [self.initial_docx_path, self.initial_json_path, self.initial_audio_path]
        ):
            # Use root.after to run this just after the main window appears
            self.root.after(100, self._auto_load_files)

    def _setup_ui(self):
        # (UI setup is the same as before, no changes needed here)
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
        self.text_widget.bind("<Button-1>", self.click_to_seek)

        control_frame = ttk.Frame(self.root, padding="10")
        control_frame.pack(fill=tk.X)
        self.play_pause_button = ttk.Button(
            control_frame, text="▶ Play", command=self.toggle_play_pause
        )
        self.play_pause_button.pack(side=tk.LEFT, padx=5)
        ttk.Button(control_frame, text="⏮ 5s", command=self.rewind).pack(
            side=tk.LEFT, padx=5
        )

    # ### NEW: Function to handle auto-loading from CLI ###
    def _auto_load_files(self):
        logging.info("CLI arguments provided. Attempting to auto-load files.")
        self.loaded_files_label.config(text="Auto-loading files from command line...")
        self.root.update()

        try:
            # Directly use the paths provided during initialization
            self.audio_file_path = self.initial_audio_path
            self._process_files(
                self.initial_docx_path, self.initial_json_path, self.initial_audio_path
            )
            self.loaded_files_label.config(
                text=f"Ready to review: {os.path.basename(self.initial_docx_path)}"
            )
            # Disable the load button since we successfully loaded
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
        # This function remains as the manual fallback
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
        """A centralized function to handle the core processing logic."""
        try:
            logging.info(f"Processing DOCX: {docx_path}")
            self._parse_docx(docx_path)

            logging.info(f"Processing JSON: {json_path}")
            self._parse_json(json_path)

            self.display_full_text()
            self._create_word_map()

            logging.info(f"Loading audio: {audio_path}")
            pygame.mixer.music.load(audio_path)

            logging.info("Processing complete. Ready for playback.")
        except Exception as e:
            logging.error(f"Failed during file processing: {e}", exc_info=True)
            messagebox.showerror(
                "Error",
                f"Failed to process files: {e}\n\nSee review_app.log for details.",
            )
            self.loaded_files_label.config(
                text="Error loading files. Please try again."
            )

    def _parse_docx(self, path):
        """
        Parses the entire DOCX document, including paragraphs and tables,
        maintaining the original document order.
        """
        logging.info("Starting advanced DOCX parsing (including tables).")
        doc = docx.Document(path)

        all_text_blocks = []

        # We iterate through the document's body to get both paragraphs and tables in order
        # doc._body is the high-level wrapper; doc._body._element is the underlying XML object
        # ### FIX: Removed the extra .body attribute that caused the crash ###
        for block in doc._body._element.iterchildren():

            # Check if the block is a paragraph
            if isinstance(block, docx.oxml.text.paragraph.CT_P):
                # Re-constitute the Paragraph object from its XML element and parent
                para = docx.text.paragraph.Paragraph(block, doc._body)
                if para.text.strip():
                    all_text_blocks.append(para.text)

            # Check if the block is a table
            elif isinstance(block, docx.oxml.table.CT_Tbl):
                logging.info("Found a table in the document. Extracting cell text.")
                # Re-constitute the Table object from its XML element and parent
                table = docx.table.Table(block, doc._body)
                # Iterate through rows, then cells (left-to-right, top-to-bottom)
                for row in table.rows:
                    for cell in row.cells:
                        # We can just get the text directly from the cell
                        if cell.text.strip():
                            # Treat each cell as its own paragraph
                            all_text_blocks.append(cell.text)

        # Join all collected text blocks into a single string for display
        self.full_manuscript_text = "\n\n".join(all_text_blocks)

        # Tokenize the newly created full text for the word map
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
            data = json.load(f)  # Load the entire JSON object first

        # --- FIX: Specifically assign the list from the 'words' key ---
        self.transcribed_data = data["words"]

        logging.info(
            f"Loaded {len(self.transcribed_data)} transcribed words from JSON."
        )

    def _create_word_map(self):
        logging.info("Starting alignment to create word map.")
        self.word_map = {}
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
                logging.debug(
                    f"Opcode: {tag}, Manuscript slice: {i1}:{i2}, Whisper slice: {j1}:{j2}"
                )
                for i in range(i2 - i1):
                    manuscript_index = i1 + i
                    whisper_index = j1 + i
                    token = self.manuscript_tokens[manuscript_index]
                    start_char, end_char = token["start"], token["end"]
                    tk_start = f"1.0 + {start_char} chars"
                    tk_end = f"1.0 + {end_char} chars"
                    self.word_map[whisper_index] = (tk_start, tk_end)
        logging.info(
            f"Word map created. Mapped {len(self.word_map)} of {len(self.transcribed_data)} transcribed words."
        )

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

    def rewind(self, seconds=5.0):
        current_pos = (pygame.mixer.music.get_pos() / 1000.0) + self.playback_offset
        new_start = max(0, current_pos - seconds)
        logging.info(f"Rewinding from {current_pos:.2f}s to {new_start:.2f}s.")
        self.seek_to(new_start)

    def click_to_seek(self, event):
        tk_index = self.text_widget.index(f"@{event.x},{event.y}")
        char_index = int(tk_index.split(".")[1])
        clicked_token_idx = -1
        for i, token in enumerate(self.manuscript_tokens):
            if token["start"] <= char_index < token["end"]:
                clicked_token_idx = i
                break
        if clicked_token_idx != -1:
            for whisper_idx, (start, end) in self.word_map.items():
                if self.text_widget.index(start) == self.text_widget.index(
                    f"1.0 + {self.manuscript_tokens[clicked_token_idx]['start']} chars"
                ):
                    start_time = self.transcribed_data[whisper_idx]["start"]
                    logging.info(f"User clicked, seeking to {start_time:.2f}s")
                    self.seek_to(start_time)
                    return

    def seek_to(self, time_in_seconds):
        self.reset_highlighter_state()
        pygame.mixer.music.play(start=time_in_seconds)
        self.playback_offset = time_in_seconds
        if not self.is_playing:
            self.is_playing = True
            self.play_pause_button.config(text="⏸ Pause")
            self.update_highlight()

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
                    logging.debug(
                        f"Time={current_time:.2f}s. Highlighting word '{word_data['word']}' (index {i}) at {tk_start}-{tk_end}"
                    )
                    self.text_widget.tag_add("current_word", tk_start, tk_end)
                    self.text_widget.see(tk_start)
                else:
                    logging.debug(
                        f"Time={current_time:.2f}s. Word '{word_data['word']}' (index {i}) not in map (likely an insertion)."
                    )
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


# ### NEW: Main block with argparse for CLI ###
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
