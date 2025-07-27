import tkinter as tk
from tkinter import filedialog, ttk, messagebox, Menu
import json
import docx
import pygame
import difflib
import csv
import os
import threading
import time


# --- Normalization Function ---
# This is crucial for comparing words accurately. It removes leading/trailing
# punctuation and whitespace and converts to lowercase.
def normalize_word(word):
    # Also handles leading spaces from Whisper's output
    return word.lower().strip(".,;:!?\"'()[]{} ")


class AudiobookReviewApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Audiobook Narrator Review Tool")
        self.root.geometry("1000x700")

        # --- Initialize Core Components ---
        pygame.init()
        pygame.mixer.init()

        # --- Data Storage ---
        self.audio_file_path = None
        self.manuscript_words = []
        self.transcribed_data = []
        self.mismatches = []
        self.is_playing = False
        self.playback_offset = 0

        ### --- CHANGE: Switched from paragraph logic to full text and highlighter state ---
        self.full_manuscript_text = ""
        self.last_highlighted_word_index = -1
        self.last_highlight_tk_end_index = "1.0"
        self.after_id = None  # To control the update loop

        # --- UI Setup ---
        self._setup_ui()

    def _setup_ui(self):
        # --- Top Frame for File Selection ---
        top_frame = ttk.Frame(self.root, padding="10")
        top_frame.pack(fill=tk.X)

        ttk.Button(top_frame, text="Load Files...", command=self.load_files).pack(
            side=tk.LEFT
        )
        self.loaded_files_label = ttk.Label(
            top_frame, text="Please load Manuscript, JSON, and Audio files."
        )
        self.loaded_files_label.pack(side=tk.LEFT, padx=10)

        # --- Main Text View ---
        text_frame = ttk.Frame(self.root, padding="10")
        text_frame.pack(expand=True, fill=tk.BOTH)

        self.text_widget = tk.Text(
            text_frame, wrap=tk.WORD, font=("Helvetica", 14), spacing1=5, spacing3=10
        )
        self.text_widget.pack(expand=True, fill=tk.BOTH, side=tk.LEFT)

        # Add a scrollbar
        scrollbar = ttk.Scrollbar(text_frame, command=self.text_widget.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.text_widget.config(yscrollcommand=scrollbar.set)

        # Configure tags for highlighting
        self.text_widget.tag_configure(
            "substitution", background="#FFDDDD"
        )  # Light Red
        self.text_widget.tag_configure("insertion", background="#DDFFDD")  # Light Green
        self.text_widget.tag_configure(
            "deletion", background="#FFFFCC", overstrike=True
        )  # Yellow with strikethrough
        self.text_widget.tag_configure("current_word", background="lightblue")

        self.text_widget.bind("<Button-1>", self.click_to_seek)

        # --- Bottom Control Frame ---
        control_frame = ttk.Frame(self.root, padding="10")
        control_frame.pack(fill=tk.X)

        # Playback Controls
        self.play_pause_button = ttk.Button(
            control_frame, text="▶ Play", command=self.toggle_play_pause
        )
        self.play_pause_button.pack(side=tk.LEFT, padx=5)
        ttk.Button(control_frame, text="⏮ 5s", command=self.rewind).pack(
            side=tk.LEFT, padx=5
        )

        # Playback Speed
        ttk.Label(control_frame, text="Speed:").pack(side=tk.LEFT, padx=(10, 0))
        self.speed_var = tk.DoubleVar(value=1.0)
        speed_menu = ttk.OptionMenu(
            control_frame, self.speed_var, 1.0, 0.75, 1.0, 1.25, 1.5
        )
        speed_menu.pack(side=tk.LEFT, padx=5)

        ### --- CHANGE: Removed paragraph navigation buttons ---

        # --- Right Panel (Placeholder for now) ---
        right_panel = ttk.Frame(self.root, width=150, padding="10")
        right_panel.pack(fill=tk.Y, side=tk.RIGHT)
        ttk.Label(right_panel, text="Controls").pack()

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

        try:
            self._parse_docx(docx_path)
            self._parse_json(json_path)
            self.display_full_text()
            pygame.mixer.music.load(self.audio_file_path)
            self.loaded_files_label.config(
                text=f"Ready to review: {os.path.basename(docx_path)}"
            )
        except Exception as e:
            messagebox.showerror("Error", f"Failed to process files: {e}")
            self.loaded_files_label.config(
                text="Error loading files. Please try again."
            )

    ### --- CHANGE: Parses entire document into one string ---
    def _parse_docx(self, path):
        doc = docx.Document(path)
        # Join paragraphs with double newlines for spacing
        self.full_manuscript_text = "\n\n".join(
            [p.text for p in doc.paragraphs if p.text.strip()]
        )
        # Keep manuscript_words for the diff comparison (though we are not using it visually for now)
        self.manuscript_words = [
            normalize_word(w)
            for w in self.full_manuscript_text.split()
            if normalize_word(w)
        ]

    def _parse_json(self, path):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.transcribed_data = data["words"]

    ### --- CHANGE: Displays the full manuscript text ---
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
        else:
            if self.playback_offset > 0:
                pygame.mixer.music.unpause()
            else:
                self.reset_highlighter_state()
                pygame.mixer.music.play()
            self.is_playing = True
            self.play_pause_button.config(text="⏸ Pause")
            self.update_highlight()

    ### --- CHANGE: Resets highlighter state for sequential searching ---
    def reset_highlighter_state(self):
        self.last_highlighted_word_index = -1
        self.last_highlight_tk_end_index = "1.0"
        self.text_widget.tag_remove("current_word", "1.0", tk.END)

    def rewind(self):
        current_pos = pygame.mixer.music.get_pos() / 1000.0
        new_start = max(0, current_pos - 5.0)

        self.reset_highlighter_state()  # Reset state before seeking
        pygame.mixer.music.play(start=new_start)
        self.playback_offset = new_start  # Store the seek position

        if not self.is_playing:
            self.is_playing = True
            self.play_pause_button.config(text="⏸ Pause")
            self.update_highlight()

    def click_to_seek(self, event):
        # A simple seek implementation. More advanced logic is needed for perfect accuracy.
        char_index_clicked = self.text_widget.index(f"@{event.x},{event.y}")
        chars_from_start = len(self.text_widget.get("1.0", char_index_clicked))
        total_chars = len(self.full_manuscript_text)

        # Estimate word position and find a corresponding timestamp
        word_index_estimate = int(
            (chars_from_start / total_chars) * len(self.transcribed_data)
        )
        word_index_estimate = min(word_index_estimate, len(self.transcribed_data) - 1)

        start_time = self.transcribed_data[word_index_estimate]["start"]

        self.reset_highlighter_state()
        pygame.mixer.music.play(start=start_time)
        self.playback_offset = start_time

        if not self.is_playing:
            self.is_playing = True
            self.play_pause_button.config(text="⏸ Pause")
            self.update_highlight()

    ### --- CHANGE: The new, stateful, sequential highlighting logic ---
    def update_highlight(self):
        if not self.is_playing:
            return

        current_time = (pygame.mixer.music.get_pos() / 1000.0) + self.playback_offset

        # Search for the word in the transcription data starting from where we left off
        for i in range(
            self.last_highlighted_word_index + 1, len(self.transcribed_data)
        ):
            word_data = self.transcribed_data[i]

            if word_data["start"] <= current_time < word_data["end"]:
                # This is the correct word. Avoid re-highlighting the same word.
                if i == self.last_highlighted_word_index:
                    break

                self.text_widget.config(state=tk.NORMAL)
                self.text_widget.tag_remove("current_word", "1.0", tk.END)

                # Search for the word in the Text widget, starting from the END of the last highlight
                word_to_find = normalize_word(word_data["word"])
                start_pos = self.text_widget.search(
                    word_to_find,
                    self.last_highlight_tk_end_index,
                    stopindex=tk.END,
                    nocase=True,
                )

                if start_pos:
                    end_pos = f"{start_pos}+{len(word_to_find)}c"
                    self.text_widget.tag_add("current_word", start_pos, end_pos)

                    # Auto-scroll to keep the highlighted word in view
                    self.text_widget.see(start_pos)

                    # Update state for the next search
                    self.last_highlight_tk_end_index = end_pos
                    self.last_highlighted_word_index = i

                self.text_widget.config(state=tk.DISABLED)
                break  # Found the word for the current timestamp, exit loop

        # Schedule the next update
        self.after_id = self.root.after(100, self.update_highlight)

    def on_closing(self):
        pygame.mixer.quit()
        pygame.quit()
        if self.after_id:
            self.root.after_cancel(self.after_id)
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = AudiobookReviewApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()
