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
    return word.lower().strip(".,;:!?\"'()[]{}")


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
        self.current_paragraph_index = 0
        self.paragraphs = []
        self.is_playing = False
        self.playback_offset = 0

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

        # Configure tags for highlighting
        self.text_widget.tag_configure(
            "substitution", background="#FFDDDD"
        )  # Light Red
        self.text_widget.tag_configure("insertion", background="#DDFFDD")  # Light Green
        self.text_widget.tag_configure(
            "deletion", background="#FFFFCC", overstrike=True
        )  # Yellow with strikethrough
        self.text_widget.tag_configure("current_word", background="lightblue")

        self.text_widget.bind(
            "<Button-1>", self.click_to_seek
        )  # Left-click to jump audio
        self.text_widget.bind(
            "<Button-3>", self._show_context_menu
        )  # Right-click for options

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

        # Paragraph Navigation
        ttk.Button(
            control_frame, text="Prev Para", command=lambda: self.navigate_paragraph(-1)
        ).pack(side=tk.LEFT, padx=5)
        ttk.Button(
            control_frame, text="Next Para", command=lambda: self.navigate_paragraph(1)
        ).pack(side=tk.LEFT, padx=5)

        # --- Right Panel for Mismatches & Export ---
        right_panel = ttk.Frame(self.root, padding="10")
        right_panel.pack(fill=tk.Y, side=tk.RIGHT)

        ttk.Label(
            right_panel, text="Confidence Threshold:", font=("Helvetica", 10, "bold")
        ).pack(pady=(0, 5))
        self.sensitivity_slider = ttk.Scale(
            right_panel,
            from_=0,
            to=100,
            orient=tk.HORIZONTAL,
            command=self._update_display_for_sensitivity,
        )
        self.sensitivity_slider.set(70)  # Default to 70% confidence
        self.sensitivity_slider.pack(fill=tk.X, pady=5)

        ttk.Button(
            right_panel,
            text="Export Confirmed Errors (CSV)",
            command=self.export_to_csv,
        ).pack(pady=20, fill=tk.X)

    def load_files(self):
        # Using askopenfilenames to select all three at once is tricky for users.
        # Let's guide them one by one.
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
            # Load and parse data
            self._parse_docx(docx_path)
            self._parse_json(json_path)

            # Core logic
            self._compare_texts()

            # UI Update
            self.display_paragraph()

            # Load audio
            pygame.mixer.music.load(self.audio_file_path)
            self.loaded_files_label.config(
                text=f"Ready to review: {os.path.basename(docx_path)}"
            )
        except Exception as e:
            messagebox.showerror("Error", f"Failed to process files: {e}")
            self.loaded_files_label.config(
                text="Error loading files. Please try again."
            )

    def _parse_docx(self, path):
        doc = docx.Document(path)
        self.paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        full_text = "\n".join(self.paragraphs)
        self.manuscript_words = [
            normalize_word(w) for w in full_text.split() if normalize_word(w)
        ]

    def _parse_json(self, path):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Store the full data, including start/end times and probability
        self.transcribed_data = data["words"]

    def _compare_texts(self):
        transcribed_words_normalized = [
            normalize_word(item["word"]) for item in self.transcribed_data
        ]
        matcher = difflib.SequenceMatcher(
            None, self.manuscript_words, transcribed_words_normalized
        )

        self.mismatches = []
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                continue

            manuscript_chunk = self.manuscript_words[i1:i2]
            narrated_chunk_data = self.transcribed_data[j1:j2]

            confidence = 1.0  # Default for deletions
            if narrated_chunk_data:
                # Average confidence of the words in the chunk
                probs = [w.get("probability", 0.0) for w in narrated_chunk_data]
                confidence = sum(probs) / len(probs) if probs else 0.0

            self.mismatches.append(
                {
                    "type": tag,  # 'replace', 'delete', 'insert'
                    "manuscript_text": " ".join(manuscript_chunk),
                    "narrated_text": " ".join([w["word"] for w in narrated_chunk_data]),
                    "start_time": (
                        narrated_chunk_data[0]["start"]
                        if narrated_chunk_data
                        else self.transcribed_data[j1 - 1]["end"]
                    ),
                    "confidence": confidence,
                    "manuscript_indices": (i1, i2),
                    "status": "unconfirmed",  # 'confirmed', 'ignored'
                }
            )

    def display_paragraph(self):
        self.text_widget.config(state=tk.NORMAL)
        self.text_widget.delete(1.0, tk.END)

        if not self.paragraphs:
            return

        para_text = self.paragraphs[self.current_paragraph_index]
        self.text_widget.insert(tk.END, para_text)

        # Apply tags after text is inserted
        self._update_display_for_sensitivity(None)
        self.text_widget.config(state=tk.DISABLED)

    def _update_display_for_sensitivity(self, _=None):
        threshold = self.sensitivity_slider.get() / 100.0

        # Clear existing mismatch tags
        for tag in ["substitution", "insertion", "deletion"]:
            self.text_widget.tag_remove(tag, 1.0, tk.END)

        para_text = self.paragraphs[self.current_paragraph_index]
        para_start_char_index = sum(
            len(p) + 1 for p in self.paragraphs[: self.current_paragraph_index]
        )

        for mismatch in self.mismatches:
            if mismatch["confidence"] >= threshold and mismatch["status"] != "ignored":
                # This is a simplified approach to find word positions.
                # A more robust solution would use character indices from the start.
                # For now, we find the first occurrence in the paragraph.

                # We need to find the char position of the mismatch in the text widget
                text_to_find = (
                    mismatch["manuscript_text"]
                    if mismatch["type"] != "insert"
                    else mismatch["narrated_text"]
                )
                start_pos = para_text.find(text_to_find)

                if start_pos != -1:
                    start_tk_index = f"1.{start_pos}"
                    end_tk_index = f"{start_tk_index}+{len(text_to_find)}c"

                    tag_name = ""
                    if mismatch["type"] == "replace":
                        tag_name = "substitution"
                    elif mismatch["type"] == "delete":
                        tag_name = "deletion"

                    if tag_name:
                        self.text_widget.tag_add(tag_name, start_tk_index, end_tk_index)

    def toggle_play_pause(self):
        if self.is_playing:
            pygame.mixer.music.pause()
            self.is_playing = False
            self.play_pause_button.config(text="▶ Play")
        else:
            if self.playback_offset > 0:
                pygame.mixer.music.unpause()
            else:  # Starting from beginning or after a stop
                pygame.mixer.music.play()

            self.is_playing = True
            self.play_pause_button.config(text="⏸ Pause")
            # Start the karaoke highlighter loop
            self.update_highlight()

    def rewind(self):
        current_pos = pygame.mixer.music.get_pos() / 1000.0
        new_start = max(0, current_pos - 5.0)
        pygame.mixer.music.play(start=new_start)
        self.playback_offset = new_start
        if not self.is_playing:
            self.is_playing = True
            self.play_pause_button.config(text="⏸ Pause")
            self.update_highlight()

    def navigate_paragraph(self, direction):
        new_index = self.current_paragraph_index + direction
        if 0 <= new_index < len(self.paragraphs):
            self.current_paragraph_index = new_index
            self.display_paragraph()

    def click_to_seek(self, event):
        index = self.text_widget.index(f"@{event.x},{event.y}")
        char_num = int(index.split(".")[1])

        # Find which word in the transcribed data corresponds to this character
        # This is a complex mapping; a simpler way is to find the nearest timestamp
        # based on word position in the paragraph.
        # Let's find the word clicked on and find its counterpart in the JSON.
        clicked_word = normalize_word(
            self.text_widget.get(f"{index} wordstart", f"{index} wordend")
        )

        # Find the first occurrence of this word in the transcription data
        for word_data in self.transcribed_data:
            if normalize_word(word_data["word"]) == clicked_word:
                start_time = word_data["start"]
                pygame.mixer.music.play(start=start_time)
                if not self.is_playing:
                    self.is_playing = True
                    self.play_pause_button.config(text="⏸ Pause")
                    self.update_highlight()
                break

    def update_highlight(self):
        if not self.is_playing:
            return

        current_time = (pygame.mixer.music.get_pos() / 1000.0) + self.playback_offset
        self.text_widget.tag_remove("current_word", 1.0, tk.END)

        # Find the current word in the transcribed data
        for word_data in self.transcribed_data:
            if word_data["start"] <= current_time < word_data["end"]:
                # Now find this word in the text widget and highlight it
                word_to_find = word_data["word"].strip()
                start_pos = self.text_widget.get(1.0, tk.END).find(word_to_find)
                if start_pos != -1:
                    start_tk_index = f"1.{start_pos}"
                    end_tk_index = f"{start_tk_index}+{len(word_to_find)}c"
                    self.text_widget.tag_add(
                        "current_word", start_tk_index, end_tk_index
                    )
                break

        # Loop this function
        self.root.after(100, self.update_highlight)

    def _show_context_menu(self, event):
        # A proper implementation would find the exact mismatch under the cursor.
        # This is a placeholder to show the menu.
        context_menu = Menu(self.root, tearoff=0)
        context_menu.add_command(
            label="Confirm as Error",
            command=lambda: self.set_mismatch_status("confirmed", event),
        )
        context_menu.add_command(
            label="Ignore (False Positive)",
            command=lambda: self.set_mismatch_status("ignored", event),
        )
        context_menu.tk_popup(event.x_root, event.y_root)

    def set_mismatch_status(self, status, event):
        # This needs to be implemented by finding which mismatch was clicked.
        # For this example, we'll just print it.
        print(f"Set mismatch status to '{status}' (Feature to be fully implemented)")
        # In a full app, you'd identify the mismatch and update its 'status' in self.mismatches
        # then call self._update_display_for_sensitivity() to refresh the view.

    def export_to_csv(self):
        save_path = filedialog.asksaveasfilename(
            defaultextension=".csv", filetypes=[("CSV file", "*.csv")]
        )
        if not save_path:
            return

        # This is a simplified export. A full implementation would use the 'status' field.
        confirmed_errors = [m for m in self.mismatches if m["status"] == "confirmed"]
        if not confirmed_errors:
            confirmed_errors = (
                self.mismatches
            )  # For demo, export all if none are confirmed

        try:
            with open(save_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(
                    [
                        "Timestamp",
                        "Error Type",
                        "Manuscript Text",
                        "Narrated Text",
                        "Confidence",
                    ]
                )
                for error in confirmed_errors:
                    writer.writerow(
                        [
                            time.strftime("%H:%M:%S", time.gmtime(error["start_time"])),
                            error["type"],
                            error["manuscript_text"],
                            error["narrated_text"],
                            f"{error['confidence']:.2%}",
                        ]
                    )
            messagebox.showinfo("Success", f"Report saved to {save_path}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save CSV: {e}")

    def on_closing(self):
        pygame.mixer.quit()
        pygame.quit()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = AudiobookReviewApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()
